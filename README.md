Poloniex Futures Strategy Pack
--------
--------

Sample algo-trade strategies for Poloniex futures. 

DISCLAIMER: 

```
USE AT YOUR OWN RISK. This code is intended for demonstration purposes only, the scripts contained demonstrate the basics of interacting with the Poloniex API through a practical example. 
We do not endorse or recommend that you use these scripts or the sample strategies they contain in a production environment. 
As these have not been backtested for profitability, you should expect to lose money if you use them. 
Poloniex is not responsible for any losses you may incur when using these scripts.
```

Getting Started
--------

These instructions will get a copy of the project up and running on your local machine for development and testing purposes. 

Prerequisites and Installation
--------

It is recommended to run this strategy in a virtual environment. Once an environment is setup, install TA-LIB.

```bash
python3 -m venv tutorial-env
source ~/tutorial-env/bin/activate
install TA-lib prerequisites - https://github.com/mrjbq7/ta-lib
pip install requirements.txt
```

Once all the dependencies for TA-lib are installed, get the code files with git.

Clone the repo into the path you will be using
```bash
git clone <REPO LOCATION>
```

Configuration
--------

All trade configurations are done in the trading file. Account keys and passwords are set in environment variables. 

WARNING: Do not leave secrets or passwords as plain text.

```python
# Trading parameters
SYMBOL = 'BTCUSDTPERP'
LEVERAGE = '25'
TRADE_SIZE = 50
MAX_SLIPPAGE = 0.025
```

Tweak the sensitivity of the algorithm or update the strategy in the `trade_signal` function

```python
self.rsif(14) # 14 RSI period window
self.bbp(20, 2, 2, 0) # 20 period Bollinger Band window
```

Running the tests
--------

Run `python sample-RSIBBP.py or python sample-MOM.py`

Bot should take a moment to open connections and subscribe to channels.

```
Latest Signals:
                        open    high     low   close   size        RSI       BBP Signal Position
ts                                                                                             
2020-06-08 19:35:00  9704.0  9707.0  9704.0  9707.0  10793  46.165048  0.258199      0      buy
2020-06-08 19:35:30  9702.0  9706.0  9702.0  9706.0   8596  44.709798  0.203153      0      buy
2020-06-08 19:36:00  9702.0  9704.0  9702.0  9704.0   6364  41.867217  0.098853      0      buy
2020-06-08 19:36:30  9704.0  9705.0  9702.0  9705.0   3562  43.791491  0.206852      0      buy
2020-06-08 19:37:00  9704.0  9704.0  9704.0  9704.0   2432  42.284161  0.170238      0      buy

```
If a position is open, the following is expected.
```
Current Position:
Position 475
Entry Price 9680.37
liquidation Price 9354.0
Unrealised Pnl 6.11%
```
Else, the default output is
```
Current Position:
Position 0
Entry Price 0
liquidation Price 0
Unrealised Pnl 0%
```
