import os
import asyncio
from threading import Thread
import math

import websockets, json, numpy
import config
from binance.client import Client
from binance.enums import *

import discord

coins = [
    "ADA",
    "STORJ",
    "BAT",
    "VET",
    "ONE",
    "ONT",
    "UNI",
    "ZEN",
    "OXT",
    "QTUM",
    "SOL",
    "BAND",
    "NEO",
    "XLM",
    "ATOM",
    "ZRX",
    "KNC",
    "HNT",
    "MATIC",
    "LINK",
    "MANA",
    "ENJ",
    "IOTA",
    "ZIL",
    "HBAR",
    "RVN",
    "WAVES",
    "OMG",
    "XTZ",
    "ALGO",
    "REP"
]

precisions = {
    "ADA": 10.0,
    "STORJ": 100.0,
    "BAT": 100.0,
    "VET": 1.0,
    "ONE": 10.0,
    "ONT": 100.0,
    "UNI": 100.0,
    "DOGE": 1.0,
    "ZEN": 1000.0,
    "OXT": 100.0,
    "QTUM": 1000.0,
    "SOL": 100.0,
    "BAND": 100.0,
    "NEO": 1000.0,
    "XLM": 10.0,
    "ATOM": 1000.0,
    "ZRX": 100.0,
    "KNC": 1000.0,
    "HNT": 1000.0,
    "MATIC": 10.0,
    "LINK": 100.0,
    "MANA": 100.0,
    "ENJ": 10.0,
    "IOTA": 100.0,
    "ZIL": 10.0,
    "HBAR": 10.0,
    "RVN": 10.0,
    "WAVES": 100.0,
    "OMG": 100.0,
    "XTZ": 100.0,
    "ALGO": 1000.0,
    "REP": 1000.0
}

precisions = { c : -1 for c in coins }

base_asset = "USD"

streams = map(lambda s: s.lower() + "usdt@kline_1m", coins)
endpoint = "/".join(streams)

SOCKET = "wss://stream.binance.com:9443/ws/" + endpoint

opens = { c : [] for c in coins }
closes = { c : [] for c in coins }
rates = { c : [] for c in coins }
prices = { c : 0 for c in coins }

last_msg = "none yet"
channel = -1 # should start with a default channel but I'm lazy

binance_client = Client(config.API_KEY, config.API_SECRET, tld='us')
discord_client = discord.Client()

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

# prints to console and discord
async def shout(msg):
    print(msg, flush=True)
    await discord_message(msg)

#########################################################################################################
# Binance Interaction
#########################################################################################################
# def binance_market_buy(pair, quantity):
#     success = False
#     tries = 0
#     max_retry = 5
#     qty = xf()
#     while (success == False and tries < max_retry):
#         try:
#             order = binance_client.order_market_sell(symbol=pair, quantity=qty)
#             success = True
#         except Exception as e:
#             success = False
#         tries += 1
#         # lower qty precision

# gets the decimal precision (LOT_SIZE) of the coin, or a default precision
# def precision(coin):
#     p = 1.0
#     if (precisions[coin] == -1):
#         pair = coin + "USDT"
#         info = binance_client.get_symbol_info(pair)
#         print("coin info = {}", info)
#         f = [i["stepSize"] for i in info["filters"] if i["filterType"] == "LOT_SIZE"][0] # annoying but does the job
#         if (f.index("1") > 0):
#             p = math.pow(10.0, f.index("1") - 1)
#             precisions[coin] = p
#         else:
#             p = 1.0
#             precisions[coin] = p
#         return p
#     else:
#         return precisions[coin]

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
            return True
        else:
            return False
    except Exception as e:
        print("an exception occured - {}".format(e))
        return False

# buys as much as possible of the given asset
async def market_buy(coin):
    bal = balance(base_asset)
    try:
        if (bal > 50.0):
            curr_price = prices[coin]
            qty = xf(coin, bal/curr_price * 0.99) # the .99 is to discount a bit in case the price has already gone beyond this
            print("Attempting market buy of {} units of {}".format(qty, coin))
            pair = coin + base_asset
            order = binance_client.order_market_buy(symbol=pair, quantity=qty)
            print(order)
            qty = xf(xyield(order))
            #qty = xf(coin, float(order['executedQty']) - float(order['fills'][0]['commission']))
            #order = client.get_order(symbol=pair,orderId=order['orderId'])
            #discord_message("Order info: {}".format(order))
            tail_price = xs(curr_price*0.98)
            print("Attempting to place tail with qty={} and price={}".format(tail_price))
            tail_order = binance_client.create_order(
                symbol=pair, 
                side='SELL', 
                type='STOP_LOSS_LIMIT', 
                timeInForce='GTC',
                quantity=qty, 
                price=tail_price,
                stopPrice=tail_price)
            #tail_order = binance_client.order_limit_sell(symbol=pair, quantity=qty, price="{:.2f}".format(tail_price))
            print(tail_order)
            await shout(":red_circle: Purchased {} at {} with sell tail at {}".format(coin, curr_price, tail_price))
        else:
            return False
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        return False
    return True

# updates (if necessary) the stop-limit-sell order of the given pair to trail 2% behind the current price
# assumption: there is at most one stop-limit order for any given pair
async def update_tail_order(coin):
    try:
        pair = coin + base_asset
        orders = binance_client.get_open_orders(symbol=pair)
        if len(orders) > 0:
            curr_price = prices[coin]
            stop_price = float(orders[0]['stopPrice'])
            if (curr_price*0.97 > stop_price): # stop_price is more than 3% away from the current price, raise it
                print("Attempting to update tail order for {}".format(coin))
                # cancel previous
                order_id = orders[0]['orderId']
                binance_client.cancel_order(symbol=pair, orderId=order_id)
                # create new
                tail_price = xs(curr_price*0.98)
                qty = xf(coin, float(orders[0]['origQty']) - float(orders[0]['executedQty']))
                tail_order = binance_client.create_order(
                    symbol=pair, 
                    side='SELL', 
                    type='STOP_LOSS_LIMIT',
                    timeInForce='GTC',
                    quantity=qty, 
                    price=tail_price,
                    stopPrice=tail_price)
                print(tail_order)
                await shout(":arrow_double_up: Updated {} tail from {} to {}".format(coin, stop_price, tail_price))
    except Exception as e:
        await shout("an exception occured - {}".format(e))

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

#########################################################################################################
# Alerting/Status Check
#########################################################################################################
async def status():
    global opens, closes, rates
    embed = discord.Embed(title="Latest coin statuses:")
    for coin in rates:
        last_2_rates = rates[coin][-2:]
        s = sum(last_2_rates)
        status = "{} rate over last 2m is {}%".format(coin, round(s*100, 3))
        print(status)
        embed.add_field(name=coin, value=status)
    await discord_embed(embed)

async def check_for_alerts(coin):
    global opens, closes, rates
    last_2_rates = rates[coin][-2:]
    s = sum(last_2_rates)
    if (s > 0.012):
        alert = ":ocean: {} (${}) over last 2m is surging {}%".format(coin, round(prices[coin], 3), round(s*100, 3))
        await discord_message(alert)
        await market_buy(coin)
    if (s < -0.02):
        alert = ":small_red_triangle_down: {} (${}) over last 2m has crashed {}%".format(coin, round(prices[coin], 3), round(s*100, 3))
        await discord_message(alert)

async def output_prices():
    global prices
    embed = discord.Embed(title="Latest coin prices:")
    for coin in rates:
        price = round(prices[coin], 3)
        embed.add_field(name=coin, value=price)
    await discord_embed(embed)

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

                    elif command.startswith("buy"):
                        second_arg = command.replace('buy','').strip()
                        if (message.author.id == config.OWNER_USERID):
                            if (second_arg in prices):
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
                    
#########################################################################################################
# Initializing & Socket Listening
#########################################################################################################
async def init_connection():
    global websocket
    websocket = await websockets.connect(SOCKET)

async def listener():
    global opens, closes, rates, prices, last_msg
    try:
        async for message in websocket:
            last_msg = message
            json_message = json.loads(message)
            candle = json_message['k']
            coin = candle['s'].replace('USDT', '')
            is_candle_closed = candle['x']
            prices[coin] = float(candle['c'])
            if is_candle_closed:
                #print(message)
                open_price = float(candle['o'])
                close_price = float(candle['c'])
                rate = (close_price/open_price) - 1.0
                opens[coin].append(open_price)
                closes[coin].append(close_price)
                rates[coin].append(rate)
                await check_for_alerts(coin)
                await update_tail_order(coin)
    except Exception as ex:
        print(ex)

if __name__ == '__main__':
    print('Initializing')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_connection())
    loop.create_task(discord_client.start(config.DISCORD_TOKEN))
    loop.create_task(listener())
    loop.run_forever()