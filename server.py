from flask import Flask, render_template, request, redirect
from core import Core
from flask_qrcode import QRcode

app = Flask(__name__)
cli = Core()
QRcode(app)

@app.route('/') 
def index():
	arr = cli.list_wallets()
	return render_template("wallets.html", wallets=arr)
	# return render_template("index.html")

@app.route('/wallets/') 
def wallets():
	arr = cli.list_wallets()
	return render_template("wallets.html", wallets=arr)

@app.route('/wallets/<name>/') 
def wallet(name):
	w = cli.get_wallet(name)
	return render_template("wallet.html", name=name, info=w.info(), balance=w.balance())

@app.route('/wallets/<name>/send/', methods=['GET', 'POST'])
def send(name):
	address = ""
	amount = 0
	unsigned_psbt = ""
	signed_psbt = ""
	print(request.form)
	if request.method == 'POST':
		address = request.form['btcaddress']
		amount = float(request.form['amount'])
		unsigned_psbt = request.form["unsignedpsbt"]
		signed_psbt = request.form["signedpsbt"]
	w = cli.get_wallet(name)
	if unsigned_psbt == "" and address != "":
		print("generating new psbt", unsigned_psbt, address)
		unsigned_psbt = w.create_psbt(address, amount)
	if signed_psbt != "" and unsigned_psbt != "":
		cli.broadcast([unsigned_psbt, signed_psbt])
		return redirect("/wallets/%s/" % name)
	return render_template("send.html", name=name, info=w.info(), balance=w.balance(), wallet=w, address=address, amount=amount, unsigned_psbt=unsigned_psbt, signed_psbt=signed_psbt)

@app.route('/wallets/<name>/receive/') 
def receive(name):
	w = cli.get_wallet(name)
	addr = w.props["addresses"][-1]
	num = len(w.props["addresses"])-1
	return render_template("receive.html", name=name, info=w.info(), balance=w.balance(), wallet=w, addr=addr, num=num)

@app.route('/wallets/<name>/receive/new/') 
def newaddr(name):
	w = cli.get_wallet(name)
	w.newaddr()
	return redirect("/wallets/%s/receive/" % name)

@app.route('/new_wallet/', methods=['GET', 'POST'])
def new_wallet():
	if request.method == 'POST':
		name = request.form['walletLabel']
		name = name.replace(" ", "_")
		xpub = request.form['walletXpub']
		error = None
		if name in cli.list_wallets():
			error = "Wallet already exists"
		if name == "":
			error = "Wallet name can't be empty"
		if error is not None:
			return render_template("new_wallet.html", error=error, name=name, xpub=xpub)
		else:
			try:
				cli.new_wallet(name, xpub)
			except:
				return render_template("new_wallet.html", error="Unknown error", name=name, xpub=xpub)				
			return redirect("/wallets/%s/" % name)
	else:
		return render_template("new_wallet.html", name="", xpub="")

if __name__ == '__main__':
	# cli.load_all_wallets()
	app.run(debug=True, port=8080)
