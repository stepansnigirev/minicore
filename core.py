import subprocess
import json
from ecc.helper import decode_base58, encode_base58_checksum
from descriptor import AddChecksum
import os, time

INIT_AMOUNT = "0.005" # amount to send to a new wallet

import sys

def run(commands):
	if sys.version_info[1] > 6:
		kwargs = {"capture_output": True}
		return subprocess.run(commands, **kwargs)
	else:
		kwargs = {"shell":True, "check":True, "stdout":subprocess.PIPE}
		return subprocess.run(" ".join(commands), **kwargs)

wallet_types = {
    # b"\x04\x88\xb2\x1e": {"descriptor": 'pkh(%s)', "testnet": False, "address_type": "legacy"},
    # b"\x04\x9d\x7c\xb2": {"descriptor": 'sh(wpkh(%s))', "testnet": False, "address_type": "p2sh-segwit"},
    # b"\x04\xb2\x47\x46": {"descriptor": 'wpkh(%s)', "testnet": False, "address_type": "bech32"},
    b"\x04\x35\x87\xcf": {"descriptor": 'pkh(%s)', "testnet": True, "address_type": "legacy"},
    b"\x04\x4a\x52\x62": {"descriptor": 'sh(wpkh(%s))', "testnet": True, "address_type": "p2sh-segwit"},
    b"\x04\x5f\x1c\xf6": {"descriptor": 'wpkh(%s)', "testnet": True, "address_type": "bech32"},
}
default_types = {
	True: b"\x04\x35\x87\xcf", # testnet
	# False: b"\x04\x88\xb2\x1e" # mainnet
}

class Wallet:
	def __init__(self, name, cli="bitcoin-cli"):
		self.name = name
		self.cli = cli.split(" ")+['-rpcwallet=%s' % name]
		self.filename = "wallets/%s.wallet" % name
		if not os.path.isfile(self.filename):
			raise Exception("Wallet '%s' doesn't exist" % name)
		try:
			with open(self.filename, "r") as f:
				content = f.read()
			self.props = json.loads(content)
		except:
			raise Exception("Wallet is corrupted")

	def info(self):
		r = run(self.cli+["getwalletinfo"])
		return json.loads(r.stdout.decode('utf-8'))

	def balance(self):
		r = run(self.cli+["getbalances"])
		return json.loads(r.stdout.decode('utf-8'))

	def newaddr(self):
		r = run(self.cli+["getnewaddress", "", self.props["address_type"]])
		addr = r.stdout.decode('utf-8').replace("\n","")
		self.props["addresses"].append(addr)
		with open("wallets/%s.wallet" % self.name, "w") as f:
			f.write(json.dumps(self.props))
		return addr

	def create_psbt(self, address, amount):
		ins = []
		balance = self.balance()
		if balance["watchonly"]["trusted"] < amount:
			r = run(self.cli+["listunspent", "0", "0"])
			txlist = json.loads(r.stdout.decode('utf-8'))
			unconfirmed = 0
			for tx in txlist:
				ins.append({"txid": tx["txid"], "vout": tx["vout"]})
				unconfirmed += tx["amount"]
				if balance["watchonly"]["trusted"]+unconfirmed > amount:
					break
		r = run(self.cli+["walletcreatefundedpsbt", json.dumps(ins), '[{"%s":%.8f}]' % (address, amount), '0', '{"includeWatching":true,"change_type":"%s"}' % self.props["address_type"], 'true'])
		print(r)
		if r.returncode != 0:
			raise Exception(r.stderr.decode("utf-8"))
		return json.loads(r.stdout.decode('utf-8'))["psbt"]

class Core:
	def __init__(self, cli="bitcoin-cli"):
		# TODO: load all wallets
		self.cli = cli.split(" ")

	def load_all_wallets(self):
		r = run(self.cli+["listwalletdir"])
		wallets_obj = json.loads(r.stdout.decode('utf-8'))
		loaded_wallets = self.list_wallets()
		wallets = [wallet["name"] for wallet in wallets_obj["wallets"]]
		for wallet in wallets:
			if wallet not in loaded_wallets and wallet != "":
				print("Loading", wallet)
				self.load_wallet(wallet)

	def load_wallet(self, name):
		name = name.replace(" ", "_")
		r = run(self.cli+["loadwallet", name])
		return json.loads(r.stdout.decode('utf-8'))

	def list_wallets(self):
		r = run(self.cli+["listwallets"])
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
		try:
			raw_xpub = decode_base58(xpub, num_bytes=82)
		except Exception as e:
			raise Exception("Wrong xpub encoding. Should be base58 encoding.")
		if raw_xpub[:4] not in wallet_types.keys():
			raise Exception("Wrong xpub format. Use testnet only.")
		obj = wallet_types[raw_xpub[:4]]
		normalized_xpub = encode_base58_checksum(default_types[obj["testnet"]]+raw_xpub[4:])
		xpub_prepared = "%s/0/*" % (normalized_xpub)
		recv_descriptor = AddChecksum(obj["descriptor"] % xpub_prepared)
		xpub_prepared = "%s/1/*" % (normalized_xpub)
		change_descriptor = AddChecksum(obj["descriptor"] % xpub_prepared)
		command = '[{"desc": "%s", "internal": false, "range": [0, 100], "timestamp": "now", "keypool": true, "watchonly": true}, {"desc": "%s", "internal": true, "range": [0, 100], "timestamp": "now", "keypool": true, "watchonly": true}]' % (recv_descriptor, change_descriptor)

		r = run(self.cli+["createwallet", name, "true"])
		print(r)
		r = run(self.cli+["-rpcwallet=%s" % name, "importmulti", command])
		print(r)
		r = run(self.cli+["-rpcwallet=%s" % name, "getnewaddress", "", obj["address_type"]])
		print(r)
		first_address = r.stdout.decode('utf-8').replace("\n", "")
		print(first_address)
		r = run(self.cli+["-rpcwallet=", "sendtoaddress", first_address, INIT_AMOUNT])
		print(r)
		o = {
			"xpub": xpub,
			"normalized_xpub": normalized_xpub,
			"address_type": obj["address_type"],
			"addresses": [first_address]
		}
		with open("wallets/%s.wallet" % name, "w") as f:
			f.write(json.dumps(o))

	def broadcast(self, psbt_arr):
		r = run(self.cli+["combinepsbt", json.dumps(psbt_arr)])
		print(r)
		if r.returncode != 0:
			raise Exception(r.stderr.decode("utf-8"))
		combined = r.stdout.decode('utf-8').replace("\n","")
		r = run(self.cli+["finalizepsbt", combined])
		print(r)
		if r.returncode != 0:
			raise Exception(r.stderr.decode("utf-8"))
		raw = json.loads(r.stdout.decode('utf-8'))
		if "hex" not in raw:
			raise Exception("Can't finalize the transaction. Are you using the right wallet?")
		r = run(self.cli+["sendrawtransaction", raw["hex"]])
		print(r)
		if r.returncode != 0:
			raise Exception(r.stderr.decode("utf-8"))

	def gentle_start(self):
		print("starting gently")
		r = run(self.cli + ["-getinfo"])
		if r.returncode == 0:
			print("bitcoind is running and everything is fine")
			return json.loads(r.stdout.decode('utf-8'))
		else:
			print("error from bitcoin-cli (err %d):" % r.returncode, r.stderr.decode('utf-8'))
		r = run(["bitcoind", "--daemon"])
		if r.returncode != 0:
			print("can't run bitcoind (err %d):" % r.returncode, r.stderr.decode('utf-8'))
			return {"error": r.stderr.decode('utf-8'), "errorcode": r.returncode, "reason": "bitcoind"}
		t0 = time.time()
		t = t0
		while t < t0+90:
			r = run(self.cli + ["-getinfo"])
			if r.returncode == 0:
				return json.loads(r.stdout.decode('utf-8'))
			time.sleep(0.1)
		return {"error": r.stderr.decode('utf-8'), "errorcode": r.returncode, "reason": "timeout"}


if __name__ == '__main__':
	core = Core()
	print(core.gentle_start())
	print("result:", core.list_wallets())
	core.load_all_wallets()
	print("result:", core.list_wallets())
