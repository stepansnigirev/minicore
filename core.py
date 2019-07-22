import subprocess
import json
from ecc.helper import decode_base58, encode_base58_checksum
from descriptor import AddChecksum
import os

INIT_AMOUNT = "0.001" # amount to send to a new wallet

wallet_types = {
    b"\x04\x88\xb2\x1e": {"descriptor": 'pkh(%s)', "testnet": False, "address_type": "legacy"},
    b"\x04\x9d\x7c\xb2": {"descriptor": 'sh(wpkh(%s))', "testnet": False, "address_type": "p2sh-segwit"},
    b"\x04\xb2\x47\x46": {"descriptor": 'wpkh(%s)', "testnet": False, "address_type": "bech32"},
    b"\x04\x35\x87\xcf": {"descriptor": 'pkh(%s)', "testnet": True, "address_type": "legacy"},
    b"\x04\x4a\x52\x62": {"descriptor": 'sh(wpkh(%s))', "testnet": True, "address_type": "p2sh-segwit"},
    b"\x04\x5f\x1c\xf6": {"descriptor": 'wpkh(%s)', "testnet": True, "address_type": "bech32"},
}
default_types = {
	True: b"\x04\x35\x87\xcf", # testnet
	False: b"\x04\x88\xb2\x1e" # mainnet
}

class Wallet:
	def __init__(self, name, cli="bitcoin-cli"):
		self.name = name
		self.cli = cli.split(" ")+['-rpcwallet=%s' % name]
		self.filename = "wallets/%s.wallet" % name
		with open(self.filename, "r") as f:
			content = f.read()
		self.props = json.loads(content)

	def info(self):
		r = subprocess.run(self.cli+["getwalletinfo"], capture_output=True)
		return json.loads(r.stdout.decode('utf-8'))

	def balance(self):
		r = subprocess.run(self.cli+["getbalances"], capture_output=True)
		return json.loads(r.stdout.decode('utf-8'))

	def newaddr(self):
		r = subprocess.run(self.cli+["getnewaddress", "", self.props["address_type"]], capture_output=True)
		addr = r.stdout.decode('utf-8').replace("\n","")
		self.props["addresses"].append(addr)
		with open("wallets/%s.wallet" % self.name, "w") as f:
			f.write(json.dumps(self.props))
		return addr

	def create_psbt(self, address, amount):
		ins = []
		balance = self.balance()
		if balance["watchonly"]["trusted"] < amount:
			r = subprocess.run(self.cli+["listunspent", "0", "0"], capture_output=True)
			txlist = json.loads(r.stdout.decode('utf-8'))
			unconfirmed = 0
			for tx in txlist:
				ins.append({"txid": tx["txid"], "vout": tx["vout"]})
				unconfirmed += tx["amount"]
				if balance["watchonly"]["trusted"]+unconfirmed > amount:
					break
		r = subprocess.run(self.cli+["walletcreatefundedpsbt", json.dumps(ins), '[{"%s":%.8f}]' % (address, amount), '0', '{"includeWatching":true,"change_type":"%s"}' % self.props["address_type"], 'true'], capture_output=True)
		print(r)
		return json.loads(r.stdout.decode('utf-8'))["psbt"]

class Core:
	def __init__(self, cli="bitcoin-cli"):
		self.cli = cli.split(" ")

	def load_all_wallets(self):
		r = subprocess.run(self.cli+["listwalletdir"], capture_output=True)
		wallets_obj = json.loads(r.stdout.decode('utf-8'))
		loaded_wallets = self.list_wallets()
		wallets = [wallet["name"] for wallet in wallets_obj["wallets"]]
		for wallet in wallets:
			if wallet not in loaded_wallets:
				print("Loading", wallet)
				self.load_wallet(wallet)

	def load_wallet(self, name):
		name = name.replace(" ", "_")
		r = subprocess.run(self.cli+["loadwallet", name], capture_output=True)
		return json.loads(r.stdout.decode('utf-8'))

	def list_wallets(self):
		r = subprocess.run(self.cli+["listwallets"], capture_output=True)
		wallets = json.loads(r.stdout.decode('utf-8'))
		files = [f[:-7] for f in os.listdir("wallets") if f[-7:]==".wallet"]
		wallets = [w for w in wallets if w.lower() in files or w in files]
		# Wallets list
		return wallets

	def get_wallet(self, name):
		name = name.replace(" ", "_")
		return Wallet(name, " ".join(self.cli))

	def new_wallet(self, name, xpub):
		name = name.replace(" ", "_")
		r = subprocess.run(self.cli+["createwallet", name, "true"], capture_output=True)
		print(r)

		raw_xpub = decode_base58(xpub, num_bytes=82)
		if raw_xpub[:4] not in wallet_types.keys():
			return render_template("new_wallet.html", error="Wrong xpub format", name=name, xpub=xpub)
		obj = wallet_types[raw_xpub[:4]]
		normalized_xpub = encode_base58_checksum(default_types[obj["testnet"]]+raw_xpub[4:])
		xpub_prepared = "%s/0/*" % (normalized_xpub)
		recv_descriptor = AddChecksum(obj["descriptor"] % xpub_prepared)
		xpub_prepared = "%s/1/*" % (normalized_xpub)
		change_descriptor = AddChecksum(obj["descriptor"] % xpub_prepared)
		command = '[{"desc": "%s", "internal": false, "range": [0, 100], "timestamp": "now", "keypool": true, "watchonly": true}, {"desc": "%s", "internal": true, "range": [0, 100], "timestamp": "now", "keypool": true, "watchonly": true}]' % (recv_descriptor, change_descriptor)

		r = subprocess.run(self.cli+["-rpcwallet=%s" % name, "importmulti", command], capture_output=True)
		print(r)
		r = subprocess.run(self.cli+["-rpcwallet=%s" % name, "getnewaddress", "", obj["address_type"]], capture_output=True)
		print(r)
		first_address = r.stdout.decode('utf-8').replace("\n", "")
		print(first_address)
		r = subprocess.run(self.cli+["-rpcwallet=", "sendtoaddress", first_address, INIT_AMOUNT], capture_output=True)
		print(r)
		o = {
			"xpub": xpub,
			"normalized_xpub": normalized_xpub,
			"address_type": obj["address_type"],
			"addresses": [first_address]
		}
		with open("wallets/%s.wallet" % name, "w") as f:
			f.write(json.dumps(o))
		# error = "Command: %s" % command
		pass

	def broadcast(self, psbt_arr):
		r = subprocess.run(self.cli+["combinepsbt", json.dumps(psbt_arr)], capture_output=True)
		print(r)
		combined = r.stdout.decode('utf-8').replace("\n","")
		r = subprocess.run(self.cli+["finalizepsbt", combined], capture_output=True)
		print(r)
		raw = json.loads(r.stdout.decode('utf-8'))["hex"]
		r = subprocess.run(self.cli+["sendrawtransaction", raw], capture_output=True)
		print(r)

if __name__ == '__main__':
	core = Core()
	print("result:", core.list_wallets())
	core.load_all_wallets()
	print("result:", core.list_wallets())
