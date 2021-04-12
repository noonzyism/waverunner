import os
import asyncio
from threading import Thread

import websockets, json, numpy, statistics
import config
from binance.client import Client
from binance.enums import *

import discord

pairs = [
    "BTCUSDT",
    "ETHUSDT",
    "ADAUSDT",
    "UNIUSDT",
    "STORJUSDT",
    "VETUSDT",
    "ONEUSDT",
    "ONTUSDT",
    "DOGEUSDT",
    "ZENUSDT",
    "OXTUSDT",
    "QTUMUSDT",
    "SOLUSDT",
    "HBARUSDT",
    "NEOUSDT",
    "XLMUSDT",
    "ATOMUSDT",
    "ZRXUSDT",
    "MANAUSDT",
    "ENJUSDT",
    "NANOUSDT",
    "ZILUSDT",
    "MATICUSDT",
    "ALGOUSDT",
    "IOTAUSDT",
    "RVNUSDT",
    "LINKUSDT"
]

streams = map(lambda s: s.lower() + "@kline_1m", pairs)
endpoint = "/".join(streams)

SOCKET = "wss://stream.binance.com:9443/ws/" + endpoint

opens = { p : [] for p in pairs }
closes = { p : [] for p in pairs }
rates = { p : [] for p in pairs }
volumes = { p : [] for p in pairs }
trades = { p : [] for p in pairs }
prices = { p : 0 for p in pairs }
messages = { p : "none yet" for p in pairs }

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
    last_3_rates = rates[pair][-3:]
    prior_30_vols = volumes[pair][-31:]
    last_vol = prior_30_vols.pop()
    prior_30_trades = trades[pair][-31:]
    last_trade = prior_30_trades.pop()
    s = sum(last_3_rates)
    if (s > 0.012):
        alert = ":fire: SURGE ALERT: {} (${}) over last 3m is up {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        if (channel != -1):
            await channel.send(alert)
    if (s < -0.02):
        alert = ":rotating_light: CRASH ALERT: {} (${}) over last 3m is down {}%".format(pair[:-4], round(prices[pair], 3), round(s*100, 3))
        if (channel != -1):
            await channel.send(alert)
    # if (len(prior_30_vols) > 1 and last_vol > 6.0*statistics.fmean(prior_30_vols)):
    #     mean = statistics.fmean(prior_30_vols)
    #     alert = ":chart_with_upwards_trend: VOLUME ALERT: {} asset volume has spiked {}x. Past minute: {}, Previous 30 minutes: {}".format(pair[:-4], round(last_vol/mean, 2), last_vol, round(mean, 3))
    #     if (channel != -1):
    #         await channel.send(alert)
    # if (len(prior_30_trades) > 1 and last_trade > 5.0*statistics.fmean(prior_30_trades)):
    #     mean = statistics.fmean(prior_30_trades)
    #     alert = ":money_with_wings: TRADE ALERT: {} trade volume has spiked {}x. Past minute: {}, Previous 30 minutes: {}".format(pair[:-4], round(last_trade/mean, 2), last_trade, round(mean, 3))
    #     if (channel != -1):
    #         await channel.send(alert)

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

async def init_connection():
    global websocket
    websocket = await websockets.connect(SOCKET)

async def listener():
    global opens, closes, rates, prices, volumes, trades, messages, last_msg
    async for message in websocket:
        last_msg = message
        json_message = json.loads(message)
        candle = json_message['k']
        pair = candle['s']
        is_candle_closed = candle['x']
        messages[pair] = message
        prices[pair] = float(candle['c'])
        if is_candle_closed:
            print(message)
            open_price = float(candle['o'])
            close_price = float(candle['c'])
            rate = (close_price/open_price) - 1.0
            volume = float(candle['v'])
            trade = float(candle['n'])
            opens[pair].append(open_price)
            closes[pair].append(close_price)
            rates[pair].append(rate)
            volumes[pair].append(volume)
            trades[pair].append(trade)
            await check_for_alerts(pair)

if __name__ == '__main__':
    print('Initializing')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_connection())
    loop.create_task(discord_client.start(config.DISCORD_TOKEN))
    loop.create_task(listener())
    loop.run_forever()