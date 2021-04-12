import os
import asyncio
from threading import Thread
import math

import websockets, json, numpy
import config
from binance.client import Client
from binance.enums import *

import discord

pairs = [
    "ADAUSDT",
    "STORJUSDT",
    "BATUSDT",
    "VETUSDT",
    "ONEUSDT",
    "ONTUSDT",
    "UNIUSDT",
    "DOGEUSDT",
    "ZENUSDT",
    "OXTUSDT",
    "QTUMUSDT",
    "SOLUSDT",
    "BANDUSDT",
    "NEOUSDT",
    "XLMUSDT",
    "ATOMUSDT",
    "ZRXUSDT",
    "KNCUSDT",
    "HNTUSDT"
]

streams = map(lambda s: s.lower() + "@kline_1m", pairs)
endpoint = "/".join(streams)

SOCKET = "wss://stream.binance.com:9443/ws/" + endpoint

opens = { p : [] for p in pairs }
closes = { p : [] for p in pairs }
rates = { p : [] for p in pairs }
prices = { p : 0 for p in pairs }

last_msg = "none yet"
channel = -1 # should start with a default channel but I'm lazy

# current/last holding data
# note: it's possible the asset this data is referencing was already sold by a stop-loss
last_bought_pair = ""   # what pair is currently being held
last_entry_price = -1    # the price the current holding was bought at
last_trail_price = -1    # the trailing stop-loss price to sell at if hit

binance_client = Client(config.API_KEY, config.API_SECRET, tld='us')
discord_client = discord.Client()

#########################################################################################################
# Helpers
#########################################################################################################
# truncates the given float to 1 decimal place, returned as a float (typically used for quantities)
# todo: make this variable precision based on pair
def xf(value):
    return int(value * 10)/10.0

# truncates the given float to 2 decimal places, returned as a string (typically used for prices)
def xs(value):
    return "{}".format(int(value * 100)/100.0)

# prints to console and discord
async def shout(msg):
    print(msg)
    await discord_message(msg)

#########################################################################################################
# Binance Interaction
#########################################################################################################
# soon...
# def order(side, quantity, symbol,order_type=ORDER_TYPE_MARKET):
#     try:
#         print("sending order")
#         order = binance_client.create_order(symbol=symbol, side=side, type=order_type, quantity=quantity)
#         print(order)
#     except Exception as e:
#         print("an exception occured - {}".format(e))
#         return False
#     return True

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

# gets the current USDT balance
def balance():
    response = binance_client.get_asset_balance(asset='USDT')
    print("Balance: {}".format(response))
    return float(response['free'])

# sells all of the given asset
async def dump(pair):
    try:
        print("Attempting to dump {}".format(pair))
        asset = pair.replace('USDT','')
        response = binance_client.get_asset_balance(asset=asset)
        print("balance: {}".format(response))
        qty = xf(float(response['free']) + float(response['locked']))
        print("qty: {}".format(qty))
        if (qty > 0):
            await cancel_tail_order(pair)
            order = binance_client.order_market_sell(symbol=pair, quantity=qty)
            print(order)
            return True
        else:
            return False
    except Exception as e:
        print("an exception occured - {}".format(e))
        return False

# buys as much as possible of the given asset
async def market_buy(pair):
    bal = balance()
    try:
        if (bal > 50.0):
            curr_price = prices[pair]
            qty = xf(bal/curr_price * 0.99) # the .99 is to discount a bit in case the price has already gone beyond this
            print("Attempting market buy of {} units of {}".format(qty, pair))
            order = binance_client.order_market_buy(symbol=pair, quantity=qty)
            qty = xf(qty * 0.99) # discounting again because actual obtained quantity may be a little less than specified - todo: use actual order quantity so we don't have to do this
            print(order)
            #order = client.get_order(symbol=pair,orderId=order['orderId'])
            last_bought_pair = pair
            #last_entry_price = float(order['fills'][0]['price']) # assumption: market order always returns filled and w/ this data
            #discord_message("Order info: {}".format(order))
            tail_price = xs(curr_price*0.98)
            print("Tail price is set to {}".format(tail_price))
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
            await shout(":red_circle: Purchased {} at {} with sell tail at {}".format(pair, curr_price, tail_price))
        else:
            return False
    except Exception as e:
        await shout("an exception occured - {}".format(e))
        return False
    return True

# updates (if necessary) the stop-limit-sell order of the given pair to trail 2% behind the current price
# assumption: there is at most one stop-limit order for any given pair
async def update_tail_order(pair):
    try:
        orders = binance_client.get_open_orders(symbol=pair)
        if len(orders) > 0:
            curr_price = prices[pair]
            stop_price = float(orders[0]['stopPrice'])
            if (curr_price*0.97 > stop_price): # stop_price is more than 3% away from the current price, raise it
                print("Attempting to update tail order for {}".format(pair))
                # cancel previous
                order_id = orders[0]['orderId']
                binance_client.cancel_order(symbol=pair, orderId=order_id)
                # create new
                tail_price = xs(curr_price*0.98)
                qty = xf(float(orders[0]['origQty']) - float(orders[0]['executedQty']))
                tail_order = binance_client.create_order(
                    symbol=pair, 
                    side='SELL', 
                    type='STOP_LOSS_LIMIT',
                    timeInForce='GTC',
                    quantity=qty, 
                    price=tail_price,
                    stopPrice=tail_price)
                print(tail_order)
                await shout(":arrow_double_up: Updated {} tail from {} to {}".format(pair, stop_price, tail_price))
    except Exception as e:
        await shout("an exception occured - {}".format(e))

# cancels the stop-limit-sell order of the given pair
# assumption: there is at most one stop-limit order for any given pair
async def cancel_tail_order(pair):
    try:
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
    for pair in rates:
        last_2_rates = rates[pair][-2:]
        s = sum(last_2_rates)
        status = "{} rate over last 2m is {}%".format(pair[:-4], round(s*100, 3))
        print(status)
        embed.add_field(name=pair[:-4], value=status)
    await discord_embed(embed)

async def check_for_alerts(pair):
    global opens, closes, rates
    last_2_rates = rates[pair][-2:]
    s = sum(last_2_rates)
    if (s > 0.012):
        alert = ":ocean: {} (${}) over last 2m is surging {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        await discord_message(alert)
        await market_buy(pair)
    if (s < -0.02):
        alert = ":small_red_triangle_down: {} (${}) over last 2m has crashed {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        await discord_message(alert)

async def output_prices():
    global prices
    embed = discord.Embed(title="Latest coin prices:")
    for pair in rates:
        price = round(prices[pair], 3)
        embed.add_field(name=pair[:-4], value=price)
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
                    if command == "waverunner":
                        await channel.send("Ready for biz :rotating_light:")

                    elif command == "latest":
                        await status()

                    elif command == "prices":
                        await output_prices()

                    elif command == "balance":
                        await discord_message("USDT balance is: {}".format(balance()))

                    elif command.startswith("buy"):
                        second_arg = command.replace('buy','').strip()
                        if (message.author.id == 127540807984087040):
                            if (second_arg in prices):
                                await market_buy(second_arg)
                            else:
                                await discord_message("Unable to purchase {}".format(second_arg))
                        else:
                            await discord_message("Sorry bud, I don't know you like that.")

                    elif command.startswith("dump"):
                        if (message.author.id == 127540807984087040):
                            second_arg = command.replace('dump','').strip()
                            success = await dump(second_arg)
                            if (success):
                                await discord_message("Dumped {}".format(second_arg))
                            else:
                                await discord_message("Couldn't dump {}".format(second_arg))
                        else:
                            await discord_message("Sorry bud, I don't know you like that.")

                    elif command.startswith("update"):
                        if (message.author.id == 127540807984087040):
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
    async for message in websocket:
        last_msg = message
        json_message = json.loads(message)
        candle = json_message['k']
        pair = candle['s']
        is_candle_closed = candle['x']
        prices[pair] = float(candle['c'])
        if is_candle_closed:
            #print(message)
            open_price = float(candle['o'])
            close_price = float(candle['c'])
            rate = (close_price/open_price) - 1.0
            opens[pair].append(open_price)
            closes[pair].append(close_price)
            rates[pair].append(rate)
            await check_for_alerts(pair)
            await update_tail_order(pair)

if __name__ == '__main__':
    print('Initializing')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_connection())
    loop.create_task(discord_client.start(config.DISCORD_TOKEN))
    loop.create_task(listener())
    loop.run_forever()