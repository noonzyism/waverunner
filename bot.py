import os
import asyncio
from threading import Thread
import math
import traceback
import datetime
from datetime import timedelta

import websockets, json, numpy, talib
import config
from binance.client import Client
from binance.enums import *

import discord

coins = [
    "ADA",
    "UNI",
    "XRP",
    "SOL",
    "SHIB",
    "DOGE",
    "MATIC",
    "LINK",
    "FTM",
    "MANA",
    "XNO",
    "AVAX",
    "SAND",
    "SUI",
    "ONE",
    "FIL",
    "CELO",
    "FET",
    "OCEAN",
    "GALA",
    "GRT",
    "NEAR",
    "ICX",
    "AUDIO",
    "ACH",
    "WAVES",
    "LPT",
    "COTI",
    "KAVA",
    "RNDR",
    "HBAR",
    "DOT",
    "VET",
    "ICP",
    "ALGO",
    "ROSE",
    "NEO"
]

precisions = {      # example quantity
    "ADA": 10.0,    # i.e. 1.2
    "UNI": 100.0,   # i.e. 1.23
    "XRP": 1.0,     # i.e. 1
    "SOL": 100.0,
    "DOGE": 1.0,
    "CELO": 10.0,
    "FET": 1.0,
    "OCEAN": 1.0,
    "MANA": 1.0,
    "XNO": 1.0,
    "AVAX": 100.0,
    "SAND": 1.0,
    "SUI": 10.0,
    "ONE": 10.0,
    "FIL": 100.0,
    "GALA": 1.0,
    "GRT": 1.0,
    "NEAR": 10.0,
    "ICX": 10.0,
    "AUDIO": 10.0,
    "ACH": 1.0,
    "WAVES": 100.0,
    "LPT": 100.0,
    "COTI": 1.0,
    "KAVA": 10.0,
    "SHIB": 1.0,
    "RNDR": 100.0,
    "MATIC": 10.0,
    "LINK": 100.0,
    "HBAR": 1.0,
    "FTM": 1.0,
    "DOT": 100.0,
    "VET": 100.0,
    "ICP": 100.0,
    "ALGO": 1.0,
    "ROSE": 10.0,
    "NEO": 100.0
}

base_asset = "USDT"

holdings = {}

MIN_HOLD_TIME = 5 # minimum time to hold a trade in minutes (not including stop loss sells)

streams = map(lambda s: s.lower() + "usdt@kline_1m", coins)
endpoint = "/".join(streams)

SOCKET = "wss://data-stream.binance.com:9443/ws/" + endpoint

data = { c : {
    "price": 0.0,
    "open": [],
    "close": [],
    "rate": [],
    "rsi-2": [],
    "rsi-4": [],
    "rsi-14": [],
    "rsi-30": []
} for c in coins }

last_msg = "none yet"
channel = -1 # should start with a default channel but I'm lazy

intents = discord.Intents.default()
intents.message_content = True

binance_client = Client(config.API_KEY, config.API_SECRET, tld='us')
discord_client = discord.Client(intents=intents)

#########################################################################################################
# Signals
#########################################################################################################
def surge(context):
    last_2_rates = context["rate"][-2:]
    s = sum(last_2_rates)
    return (s > 0.012)

def crash(context):
    last_2_rates = context["rate"][-2:]
    s = sum(last_2_rates)
    return (s < -0.03)

def rsi4_crossover(context):
    mrsi = talib.SMA(numpy.array(context["rsi-4"]), 30) if len(context["rsi-4"]) > 1 else [50.0]
    curr_rsi4 = context["rsi-4"][-1] if len(context["rsi-4"]) > 0 else 50.0
    prev_rsi4 = context["rsi-4"][-2] if len(context["rsi-4"]) > 1 else 50.0
    curr_ma30_rsi4 = mrsi[-1] if len(mrsi) > 0 else 50.0
    prev_ma30_rsi4 = mrsi[-2] if len(mrsi) > 1 else 50.0
    return (prev_rsi4 < prev_ma30_rsi4) and (curr_rsi4 > curr_ma30_rsi4) # detects a shift in momentum

def rsi4_crossunder(context):
    mrsi = talib.SMA(numpy.array(context["rsi-4"]), 30) if len(context["rsi-4"]) > 1 else [50.0]
    curr_rsi4 = context["rsi-4"][-1] if len(context["rsi-4"]) > 0 else 50.0
    prev_rsi4 = context["rsi-4"][-2] if len(context["rsi-4"]) > 1 else 50.0
    curr_ma30_rsi4 = mrsi[-1] if len(mrsi) > 0 else 50.0
    prev_ma30_rsi4 = mrsi[-2] if len(mrsi) > 1 else 50.0
    return (prev_rsi4 > prev_ma30_rsi4) and (curr_rsi4 < curr_ma30_rsi4) # detects a shift in momentum

signals = [
    surge,
    crash,
    rsi4_crossover,
    rsi4_crossunder
]

buy_criteria = [
    (surge, 0),
    (rsi4_crossover, 3)
]

sell_criteria = [
    (rsi4_crossunder, 0)
]

timeSince = { c : { s.__name__ : 9999 for s in signals } for c in coins }

#########################################################################################################
# Helpers
#########################################################################################################
# truncates the given float to N decimal places, returned as a float (typically used for quantities)
def xf(coin, value):
    p = precisions.get(coin, 1.0)
    return int(value * p)/p

# truncates the given float to 3 decimal places, returned as a string (typically used for prices)
def xs(value):
    return "{}".format(int(value * 1000)/1000.0)

# derives the total yield of a buy order, accounting for commission loss
def xyield(order):
    commission = 0.0
    for f in order['fills']:
        commission += float(f['commission'])
    return (float(order['executedQty']) - commission)

# derives the max price spent/received per coin on the given order
def xprice(order):
    price = 0.0
    for f in order['fills']:
        price = max(price, float(f['price']))
    return price

# prints to console and discord
async def shout(msg):
    print(msg, flush=True)
    await discord_message(msg)

#########################################################################################################
# Binance Interaction
#########################################################################################################
# gets the current USD balance
def balance(coin):
    response = binance_client.get_asset_balance(asset=coin)
    print("Balance: {}".format(response))
    return float(response['free'])

# sells all of the given asset
async def dump(coin):
    try:
        print("Attempting to dump {}".format(coin))
        response = binance_client.get_asset_balance(asset=coin)
        print("balance: {}".format(response))
        qty = xf(coin, float(response['free']) + float(response['locked']))
        print("qty: {}".format(qty))
        if (qty > 0):
            await cancel_tail_order(coin)
            pair = coin + base_asset
            order = binance_client.order_market_sell(symbol=pair, quantity=qty)
            print(order)
            if coin in holdings:
                buy_price = holdings[coin]['buy_price']
                cur_price = xprice(order)
                gainrate = (cur_price/buy_price) - 1.0
                await shout(":green_circle: Selling {} at {} for {}%".format(coin, cur_price, round(gainrate*100, 3)))
            holdings.pop(coin, None)
            return True
        else:
            return False
    except Exception as e:
        print("an exception occured - {}".format(e))
        traceback.print_exc()
        return False

# buys as much as possible of the given asset
async def market_buy(coin):
    bal = balance(base_asset)
    try:
        if (bal > 50.0):
            curr_price = data[coin]["price"]
            qty = xf(coin, bal/curr_price * 0.99) # the .99 is to discount a bit in case the price has already gone beyond this
            print("Attempting market buy of {} units of {}".format(qty, coin))
            pair = coin + base_asset
            order = binance_client.order_market_buy(symbol=pair, quantity=qty)
            print(order)
            buy_price = xprice(order)
            qty = xf(coin, xyield(order))
            tail_price = xs(buy_price*0.987)
            limit_price = xs(curr_price*0.95) # discounted from the trigger price to prevent holding a falling knife
            print("Attempting to place tail with qty={}, trigger={}, limit={}".format(qty, tail_price, buy_price))
            tail_order = binance_client.create_order(
                symbol=pair, 
                side='SELL', 
                type='STOP_LOSS_LIMIT', 
                timeInForce='GTC',
                quantity=qty, 
                price=limit_price,
                stopPrice=tail_price)
            print(tail_order)
            holding = { 
                "buy_price": buy_price,
                "buy_time": datetime.datetime.now()
            }
            holdings[coin] = holding
            await shout(":red_circle: Purchased {} at {} with sell tail at {}".format(coin, buy_price, tail_price))
        else:
            return False
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        traceback.print_exc()
        return False
    return True

# checks and updates holding state
async def check_if_still_holding(coin):
    try:
        if coin in holdings:
            pair = coin + base_asset
            orders = binance_client.get_open_orders(symbol=pair)
            if len(orders) <= 0:
                # coin has no tail orders, it's safe to assume this coin has been sold or is not being held
                # todo: make a dedicated more precise way of ensuring this holdings list is always in sync with reality
                holdings.pop(coin, None)
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        traceback.print_exc()

# updates (if necessary) the stop-limit-sell order of the given pair to trail 2% behind the current price
# assumption: there is at most one stop-limit order for any given pair
async def update_tail_order(coin):
    try:
        pair = coin + base_asset
        orders = binance_client.get_open_orders(symbol=pair)
        if len(orders) > 0:
            curr_price = data[coin]["price"]
            stop_price = float(orders[0]['stopPrice'])
            if (curr_price*0.97 > stop_price): # stop_price is more than 3% away from the current price, raise it
                print("Attempting to update tail order for {}".format(coin))
                # cancel previous
                order_id = orders[0]['orderId']
                binance_client.cancel_order(symbol=pair, orderId=order_id)
                # create new
                tail_price = xs(curr_price*0.98)
                lim_price = xs(curr_price*0.94)
                qty = xf(coin, float(orders[0]['origQty']) - float(orders[0]['executedQty']))
                tail_order = binance_client.create_order(
                    symbol=pair, 
                    side='SELL', 
                    type='STOP_LOSS_LIMIT',
                    timeInForce='GTC',
                    quantity=qty, 
                    price=lim_price,
                    stopPrice=tail_price)
                print(tail_order)
                await shout(":arrow_double_up: Updated {} tail from {} to {}".format(coin, stop_price, tail_price))
        else:
            # coin has no tail orders, it's safe to assume this coin has been sold or is not being held
            # todo: make a dedicated more precise way of ensuring this holdings list is always in sync with reality
            holdings.pop(coin, None)
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        traceback.print_exc()

# cancels the stop-limit-sell order of the given pair
# assumption: there is at most one stop-limit order for any given pair
async def cancel_tail_order(coin):
    try:
        pair = coin + base_asset
        orders = binance_client.get_open_orders(symbol=pair)
        if len(orders) > 0:
            order_id = orders[0]['orderId']
            binance_client.cancel_order(symbol=pair, orderId=order_id)
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        traceback.print_exc()

#########################################################################################################
# Alerting/Status Check
#########################################################################################################
async def status():
    embed = discord.Embed(title="Latest coin statuses:")
    for coin in coins[:24]:
        last_2_rates = data[coin]["rate"][-2:]
        s = sum(last_2_rates)
        status = "{} rate over last 2m is {}%".format(coin, round(s*100, 3))
        print(status)
        embed.add_field(name=coin, value=status)
    await discord_embed(embed)

async def on_candle_close(coin):
    global data, timeSince, buy_criteria, sell_criteria, MIN_HOLD_TIME
    await check_if_still_holding(coin)
    for signal in signals:
        if (signal(data[coin])):
            #await discord_message("'{}' signal detected for {}.".format(signal.__name__, coin))
            timeSince[coin][signal.__name__] = 0
            if (signal.__name__ == "surge"):
                last_2_rates = data[coin]["rate"][-2:]
                s = sum(last_2_rates)
                alert = ":ocean: {} (${}) over last 2m is surging {}%".format(coin, round(data[coin]["close"][-1], 3), round(s*100, 3))
                await discord_message(alert)
        else:
            timeSince[coin][signal.__name__] += 1

    buy = False if len(buy_criteria) <= 0 else True
    for criteria in buy_criteria:
        signal = criteria[0].__name__
        since = criteria[1]
        buy = buy and (timeSince[coin][signal] <= since)
    if (buy):
        #await discord_message("Buy criteria met for {}".format(coin))
        await market_buy(coin)

    if coin in holdings:
        buy_time = holdings[coin]['buy_time']
        cur_time = datetime.datetime.now()
        newly_bought = cur_time < buy_time + timedelta(minutes = MIN_HOLD_TIME)
        sell = False if (len(sell_criteria) <= 0 or newly_bought) else True
        for criteria in sell_criteria:
            signal = criteria[0].__name__
            since = criteria[1]
            sell = sell and (timeSince[coin][signal] <= since)
        if (sell):
            #await discord_message("Buy criteria met for {}".format(coin))
            await dump(coin)

async def output_prices():
    embed = discord.Embed(title="Latest coin prices:")
    for coin in coins[:24]:
        price = round(data[coin]["price"], 3)
        embed.add_field(name=coin, value=price)
    await discord_embed(embed)

async def output_rsis(coin):
        global data
        msg = "RSI-2: {}".format(data[coin]["rsi-2"])
        msg += " RSI-4: {}".format(data[coin]["rsi-4"])
        msg += " RSI-14: {}".format(data[coin]["rsi-14"])
        msg += " RSI-30: {}".format(data[coin]["rsi-30"])
        await shout(msg)

#########################################################################################################
# Discord Callbacks
#########################################################################################################
async def discord_message(msg):
    if (channel != -1):
        await channel.send(msg)

async def discord_embed(embed):
    if (channel != -1):
        await channel.send(embed=embed)

@discord_client.event
async def on_ready():
    print('Connected to Discord')
    await discord_client.change_presence(activity = discord.Activity(name = "the candlesticks", type = discord.ActivityType.watching))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user:
        return
    if isinstance(message.content,str):
        if len(message.content) > 0:
            if message.content[0] == "!":
                command = message.content[1:]
                try:
                    global channel, last_msg
                    channel = message.channel
                    if command == "kill":
                        if (message.author.id == config.OWNER_USERID):
                            await shout("Cya")
                            quit()

                    elif command == "latest":
                        await status()

                    elif command == "prices":
                        await output_prices()

                    elif command == "balance":
                        await discord_message("{} balance is: {}".format(base_asset, balance(base_asset)))

                    elif command == "gethype":
                        await discord_message("""**BIG GAINS ONLY** 
https://tenor.com/view/lobster-muscles-angry-spongebob-gif-11346320""")

                    elif command == "holding":
                        if (len(holdings) > 0):
                            embed = discord.Embed(title="Current holding(s):")
                            for coin in holdings:
                                buy_price = holdings[coin]['buy_price']
                                cur_price = data[coin]["price"]
                                buy_time = holdings[coin]['buy_time']
                                cur_time = datetime.datetime.now()
                                time_delta = (cur_time - buy_time).seconds/60
                                embed.add_field(name=coin, value="Purchased {} minutes ago for {} (current price: {})".format(int(time_delta), buy_price, cur_price))
                            await discord_embed(embed)
                        else:
                            await discord_message("Nothing at the moment.")

                    elif command.startswith("price"):
                        second_arg = command.replace('price','').strip()
                        if (second_arg in data):
                            await discord_message("{} price is currently {}".format(second_arg, data[second_arg]["price"]))

                    elif command.startswith("rsis"):
                        second_arg = command.replace('rsis','').strip()
                        if (second_arg in data):
                            await output_rsis(second_arg)

                    elif command.startswith("signals"):
                        second_arg = command.replace('signals','').strip()
                        if (second_arg in timeSince):
                            embed = discord.Embed(title="{} Signals:".format(second_arg))
                            for signal in timeSince[second_arg]:
                                timeAgo = timeSince[second_arg][signal]
                                msg = "{} minutes ago".format(timeAgo) if timeAgo < 9999 else "never"
                                embed.add_field(name=signal, value=msg)
                            await discord_embed(embed)

                    elif command.startswith("buy"):
                        second_arg = command.replace('buy','').strip()
                        if (message.author.id == config.OWNER_USERID):
                            if (second_arg in data):
                                await market_buy(second_arg)
                            else:
                                await discord_message("Unable to purchase {}".format(second_arg))
                        else:
                            await discord_message("Sorry bud, I don't know you like that.")

                    elif command.startswith("dump"):
                        if (message.author.id == config.OWNER_USERID):
                            second_arg = command.replace('dump','').strip()
                            success = await dump(second_arg)
                            if (success):
                                await discord_message("Dumped {}".format(second_arg))
                            else:
                                await discord_message("Couldn't dump {}".format(second_arg))
                        else:
                            await discord_message("Sorry bud, I don't know you like that.")

                    elif command.startswith("update"):
                        if (message.author.id == config.OWNER_USERID):
                            second_arg = command.replace('update','').strip()
                            await update_tail_order(second_arg)
                        else:
                            await discord_message("Sorry bud, I don't know you like that.")

                    elif command.startswith("last"):
                        second_arg = command.replace('last','').strip()
                        if (second_arg == ''):
                            await channel.send("Last message was: {}".format(last_msg))
                        elif (second_arg in messages):
                            await channel.send("Last message for {} was: {}".format(second_arg, messages[second_arg]))
                        else:
                            await channel.send("Come again?")
                except Exception as ex:
                    print(ex)
                    traceback.print_exc()
                    
#########################################################################################################
# Initializing & Socket Listening
#########################################################################################################
async def init_connection():
    global websocket
    websocket = await websockets.connect(SOCKET)

async def listener():
    global data, last_msg
    try:
        async for message in websocket:
            #print(message)
            last_msg = message
            json_message = json.loads(message)
            candle = json_message['k']
            coin = candle['s'].replace('USDT', '')
            is_candle_closed = candle['x']
            data[coin]["price"] = float(candle['c'])
            if is_candle_closed:
                open_price = float(candle['o'])
                close_price = float(candle['c'])
                high_price = float(candle['h'])
                low_price = float(candle['l'])
                rate = (close_price/open_price) - 1.0
                heikin_open = 0.5 * (data[coin]["open"][-1] + data[coin]["close"][-1]) if (len(data[coin]["open"]) > 0 and len(data[coin]["close"]) > 0) else open_price
                heikin_close = 0.25 * (open_price + high_price + low_price + close_price)
                update_data(coin, heikin_open, heikin_close, rate)
                await on_candle_close(coin)
    except Exception as ex:
        print(ex)

def update_data(coin, new_open, new_close, new_rate):
    global data

    data[coin]["open"].append(new_open)
    data[coin]["close"].append(new_close)
    data[coin]["rate"].append(new_rate)

    #print("rsi2s for {}: {}".format(coin, (data[coin]["rsi-2"])))

    rsi2 = talib.RSI(numpy.array(data[coin]["close"]), 2)
    #print("rsi2 for {}: {}".format(coin, rsi2))
    if (math.isnan(rsi2[-1]) != True):
        data[coin]["rsi-2"].append(rsi2[-1])

    rsi4 = talib.RSI(numpy.array(data[coin]["close"]), 4)
    if (math.isnan(rsi4[-1]) != True):
        data[coin]["rsi-4"].append(rsi4[-1])

    rsi14 = talib.RSI(numpy.array(data[coin]["close"]), 14)
    if (math.isnan(rsi14[-1]) != True):
        data[coin]["rsi-14"].append(rsi14[-1])

    rsi30 = talib.RSI(numpy.array(data[coin]["close"]), 30)
    if (math.isnan(rsi30[-1]) != True):
        data[coin]["rsi-30"].append(rsi30[-1])

if __name__ == '__main__':
    print('Initializing')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_connection())
    loop.create_task(discord_client.start(config.DISCORD_TOKEN))
    loop.create_task(listener())
    loop.run_forever()
