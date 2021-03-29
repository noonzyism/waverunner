import os
import asyncio
from threading import Thread

import websockets, json, numpy
import config
from binance.client import Client
from binance.enums import *

import discord

pairs = [
    "BTCUSDT",
    "ETHUSDT",
    "ADAUSDT",
    "STORJUSDT",
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
    "ZRXUSDT"
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

#binance_client = Client(config.API_KEY, config.API_SECRET, tld='us')
discord_client = discord.Client()

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

async def status():
    global opens, closes, rates
    embed = discord.Embed(title="Latest coin statuses:")
    for pair in rates:
        last_2_rates = rates[pair][-2:]
        s = sum(last_2_rates)
        status = "{} rate over last 2m is {}%".format(pair[:-4], round(s*100, 3))
        print(status)
        embed.add_field(name=pair[:-4], value=status)
    await channel.send(embed=embed)

async def check_for_alerts(pair):
    global opens, closes, rates
    last_2_rates = rates[pair][-2:]
    s = sum(last_2_rates)
    if (s > 0.012):
        alert = ":fire: SURGE ALERT: {} (${}) over last 2m is up {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        if (channel != -1):
            await channel.send(alert)
    if (s < -0.02):
        alert = ":rotating_light: CRASH ALERT: {} (${}) over last 2m is down {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        if (channel != -1):
            await channel.send(alert)

async def output_prices():
    global prices
    embed = discord.Embed(title="Latest coin prices:")
    for pair in rates:
        price = round(prices[pair], 3)
        embed.add_field(name=pair[:-4], value=price)
    await channel.send(embed=embed)

#########################################################################################################
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
                    elif command == "last":
                        await channel.send("Last message was: {}".format(last_msg))
                except Exception as ex:
                    print(ex)
                    
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
            print(message)
            open_price = float(candle['o'])
            close_price = float(candle['c'])
            rate = (close_price/open_price) - 1.0
            opens[pair].append(open_price)
            closes[pair].append(close_price)
            rates[pair].append(rate)
            await check_for_alerts(pair)

if __name__ == '__main__':
    print('Initializing')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_connection())
    loop.create_task(discord_client.start(config.DISCORD_TOKEN))
    loop.create_task(listener())
    loop.run_forever()