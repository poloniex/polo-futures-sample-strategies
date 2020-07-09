# Copyright 2020 Polo Digital Assets, Ltd.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE

import os
import asyncio
import pandas as pd
import numpy as np
from time import sleep, time

from polofutures import RestClient, WsClient

_MAX_ROWS = 500
_LAST_TRADE = 0

# Account Keys
API_KEY = os.environ['PF_API_KEY']
SECRET = os.environ['PF_SECRET']
API_PASS = os.environ['PF_PASS']

# Trading parameters
SYMBOL = 'BTCUSDTPERP'
PREFIX = 'POLO_MM'
INTERVAL = "SET INTERVAL"           # How often the MM loop runs in seconds, e.g. 15 seconds between loops
LEVERAGE = '25'                     # How much leverage you require, e.g. 25x leverage
ORDER_PAIRS = 5                     # Number of order pairs to create, e.g. 5 pairs is 10 total orders
MIN_SPREAD = "SET MINIMUM SPREAD"   # Minimum allowable spread to capture, in decimals, e.g. 0.001 is 0.1%
SPREAD_ADJUST = 0.002               # Sensitivity to spread change in decimals, e.g. 0.002 is 0.2% sensitivity
STEP_SIZE = 5                       # Order step size in lots, from starting position. e.g. first order is 5, then 10,.. 15 and so on
RISK_LIMITS = {'short': -2000, 'long': 2000} # Maximum allowable position in lots, e.g. -2000 and 2000

rest_client = RestClient(API_KEY, SECRET, API_PASS)

# Fetch Rest MarketData - Last 100 ticks
market = rest_client.market_api()
ticker = [market.get_ticker(SYMBOL)]
trade = rest_client.trade_api()


class MarketMaker:

    def __init__(self, lastest_tick):
        self.latest_tick = lastest_tick

    def open_orders(self):
        # Checks open orders on the book, and the spread from real price
        self.orders = self.orders[
            ['symbol', 'leverage', 'price', 'value', 'size', 'side', 'id', 'clientOid', 'status']].copy()
        self.orders.sort_values('price', ascending=False, inplace=True)
        self.orders['spread'] = self.orders['price'].astype(float) / self.latest_tick - 1
        self.orders.reset_index(drop=True, inplace=True)

    async def mm_loop(self):
        # This is the MM loop that runs at every set interval specified in the parameters
        self.trade_status()
        self.prepare_orders()
        self.place_orders()

    def trade_status(self):
        # Trade status updates
        self.position = trade.get_position_details(SYMBOL)
        self.orders = pd.DataFrame(trade.get_order_list(status='active')['items'])

        print(f'\n------\n'
              f'Time - {int(time())}\n'
              f'Index Price {self.latest_tick}\n'
              f'Position - {self.position["currentQty"]}\n'
              f'Current Open Orders - {self.orders.shape[0]}\n'
              f'Entry Price - {self.position["avgEntryPrice"]}\n'
              f'liquidation Price - {self.position["liquidationPrice"]}\n'
              f'Unrealised Pnl - {self.position["unrealisedRoePcnt"] * 100}%\n')

    def prepare_orders(self):
        # Prepare orders as they should be
        self.prep_orders = pd.DataFrame(
            {'orderNum': range(ORDER_PAIRS * 2), 'side': ['sell'] * ORDER_PAIRS + ['buy'] * ORDER_PAIRS})
        self.prep_orders['spread_target'] = np.where(self.prep_orders['side'] == 'sell',
                                                    MIN_SPREAD * (ORDER_PAIRS - self.prep_orders['orderNum']),
                                                    MIN_SPREAD * (ORDER_PAIRS - (1 + self.prep_orders['orderNum']))
                                                    )
        self.prep_orders['price_target'] = ((1 + self.prep_orders['spread_target']) * self.latest_tick).astype(int)
        self.prep_orders['size'] = (abs(self.prep_orders['spread_target']) * STEP_SIZE * 1000).astype(int)


        # Compare to orders that exist
        # If no orders exist, place the starter orders
        if self.orders.shape[0] == 0:
            print('No Orders Found!\nPlacing Starting Orders...')
            # print(self.prep_orders.to_string()) -- Use this for debugging

        # Else place orders based on existing
        else:
            self.open_orders()
            self.prep_orders = pd.merge(self.prep_orders, self.orders, on=['side', 'size'], how='left').fillna('No Order')
            print(self.prep_orders.to_string())

    def place_orders(self):

        for index, row in self.prep_orders.iterrows():
            if self.position["currentQty"] > RISK_LIMITS['long'] and row['side'] == 'buy':
                print(f'Long risk limit Exceeded {RISK_LIMITS["long"]}')

            elif self.position["currentQty"] < RISK_LIMITS['short'] and row['side'] == 'short':
                print(f'Short risk limit Exceeded {RISK_LIMITS["short"]}')

            else:
                clientId = f'{PREFIX}-' \
                           f'{row["side"][0]}' \
                           f'{int(row["size"])}' \
                           f'at{row["price_target"]}' \
                           f'ts{int(time())}'

                if self.orders.shape[0] < ORDER_PAIRS * 2:
                    if 'id' not in self.prep_orders or row['id'] == 'No Order':
                        orderid = trade.create_limit_order(symbol=SYMBOL,
                                                 side=row['side'],
                                                 leverage=LEVERAGE,
                                                 size=row['size'],
                                                 price=str(row['price_target']),
                                                 postOnly=True,
                                                 clientOid=clientId)
                        print(f'Order Placed! ClientID: {clientId}\tServer ID: {orderid["orderId"]}')

                if self.orders.shape[0] > 0 and row['spread'] != 'No Order':
                    # Adjust the existing orders on the book
                    spread_move = abs(row['price_target']/int(row['price']) - 1)
                    if spread_move > MIN_SPREAD*(1+SPREAD_ADJUST):
                        trade.cancel_order(row['id'])
                        orderid = trade.create_limit_order(symbol=SYMBOL,
                                                 side=row['side'],
                                                 leverage=LEVERAGE,
                                                 size=row['size'],
                                                 price=str(row['price_target']),
                                                 postOnly=True,
                                                 clientOid=clientId)
                        print(f'Order Adjusted! ClientID: {row["clientOid"]}\tServer ID: {orderid["orderId"]}')


def get_index(msg):
    if msg['topic'] == f'/contract/instrument:{SYMBOL}':
        if 'indexPrice' in msg['data']:
            global CURRENT_INDEX
            CURRENT_INDEX = msg['data']['indexPrice']
        else:
            pass


async def ws_stream():
    async def mm_async_loop():
        try:
            mm = MarketMaker(CURRENT_INDEX)
            await mm.mm_loop()
            await asyncio.sleep(INTERVAL)
        except Exception as e:
            print(f'Market Maker Error!\n'
                  f'Check Parameter Inputs\n {e}')

    await ws_client.connect()
    await ws_client.subscribe(f'/contract/instrument:{SYMBOL}')

    while True:
        await mm_async_loop()
        await asyncio.sleep(0.1)

print('Starting Market Maker!')
CURRENT_INDEX = market.get_current_mark_price(SYMBOL)['indexPrice']
ws_client = WsClient(get_index, API_KEY, SECRET, API_PASS)
loop = asyncio.get_event_loop()

try:
    loop.run_until_complete(ws_stream())
except (KeyboardInterrupt, Exception) as e:
    print(f'Stream Error\n {e}')
finally:
    print('Cancelling Orders and Shutting Down')
    trade.cancel_all_limit_orders(SYMBOL)
    print('Unsubscribing and disconnecting from websocket')
    loop.run_until_complete(ws_client.disconnect())
    loop.close()


