assets = [
    "USD",
    "ADA",
    "STORJ",
    "BAT",
    "VET",
    "ONE",
    "UNI",
    "ZEN",
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
    "DOGE"
]

class MockClient:
    def __init__(self, real_client):
        self.real_client = real_client # real client is still needed for getting real-time prices
        self.balance = start_balance
        self.balances = { a : 0 for a in assets }
        self.balances['USD'] = start_balance
        self.tails = { a : 0 for a in assets }

    def get_asset_balance(asset):
        return { 
            "free": self.balances[asset]
        }

    def order_market_sell(symbol, quantity):
        coin = symbol.replace('USD', '')
        response = self.real_client.get_avg_price(symbol)
        price = float(response['price'])
        if (self.balances[coin] >= quantity):
            self.balances['USD'] += price*quantity
            self.balances[coin] -= quantity
            return { 'fills': [
                'price': response['price']
            ]}
        else:
            raise Exception('Trying to sell more than you have!')

    def order_market_buy(symbol, quantity):
        coin = symbol.replace('USD', '')
        response = self.real_client.get_avg_price(symbol)
        price = float(response['price'])
        cost = price*quantity
        if (self.balances['USD'] >= cost):
            self.balances['USD'] -= cost
            self.balances[coin] = quantity
            return { 'fills': [
                'price': response['price']
            ]}
        else:
            raise Exception('Balance is insufficient!')

    def create_order(symbol, side, type, timeInForce, quantity, price, stopPrice):
        coin = symbol.replace('USD', '')
        self.tails[coin] = float(stopPrice)
    




