# (c) Copyright 2018 by Coinkite Inc. This file is part of Coldcard <coldcardwallet.com>
# and is covered by GPLv3 license found in COPYING.
#
# Transaction Signing. Important.
#
import time, pytest, os, random
from ckcc_protocol.protocol import CCProtocolPacker, CCProtoError, MAX_TXN_LEN, CCUserRefused
from binascii import b2a_hex, a2b_hex
from psbt import BasicPSBT, BasicPSBTInput, BasicPSBTOutput, PSBT_IN_REDEEM_SCRIPT
from io import BytesIO
from pprint import pprint, pformat
from decimal import Decimal
from base64 import b64encode, b64decode
from helpers import B2A, U2SAT, prandom, fake_dest_addr, make_change_addr, parse_change_back
from pycoin.key.BIP32Node import BIP32Node
from constants import ADDR_STYLES, ADDR_STYLES_SINGLE
from txn import *
from ckcc_protocol.constants import STXN_FINALIZE, STXN_VISUALIZE, STXN_SIGNED

@pytest.mark.parametrize('finalize', [ False, True ])
def test_sign1(dev, need_keypress, finalize):
    in_psbt = a2b_hex(open('data/p2pkh-in-scriptsig.psbt', 'rb').read())

    ll, sha = dev.upload_file(in_psbt)

    dev.send_recv(CCProtocolPacker.sign_transaction(ll, sha, finalize))


    #need_keypress('y')

    with pytest.raises(CCProtoError) as ee:
        while dev.send_recv(CCProtocolPacker.get_signed_txn(), timeout=None) == None:
            pass

    #assert 'None of the keys' in str(ee)
    assert 'require subpaths' in str(ee)


@pytest.mark.parametrize('fn', [
	'data/missing_ins.psbt',
	'data/missing_txn.psbt',
	'data/truncated.psbt',
	'data/unknowns-ins.psbt',
	'data/unknowns-ins.psbt',
])
def test_psbt_parse_fails(try_sign, fn):

    # just parse them
    with pytest.raises(CCProtoError) as ee:
        orig, result = try_sign(fn, accept=False)

    msg = ee.value.args[0]
    assert ('PSBT parse failed' in msg) or ('Invalid PSBT' in msg)

@pytest.mark.parametrize('fn', [
	'data/2-of-2.psbt',
	'data/dup_keys.psbt',
	'data/filled_scriptsig.psbt',
	'data/one-p2pkh-in.psbt',
	'data/p2pkh+p2sh+outs.psbt',
	'data/p2pkh-in-scriptsig.psbt',
	'data/p2pkh-p2sh-p2wpkh.psbt',
	'data/worked-1.psbt',
	'data/worked-2.psbt',
	'data/worked-unsigned.psbt',
	'data/worked-4.psbt',
	'data/worked-5.psbt',
	'data/worked-combined.psbt',
	'data/worked-7.psbt',
])
@pytest.mark.parametrize('accept', [True, False])
def test_psbt_parse_good(try_sign, fn, accept):
    # successful parses, but not signable

    # just parse them
    with pytest.raises(CCProtoError) as ee:
        orig, result = try_sign(fn, accept=accept)

    msg = ee.value.args[0]
    assert ('Missing UTXO' in msg) \
                or ('None of the keys' in msg) \
                or ('completely signed already' in msg) \
                or ('require subpaths' in msg), msg


# works, but annoying output
def xxx_test_sign_truncated(dev):
    ll, sha = dev.upload_file(open('data/truncated.psbt', 'rb').read())

    dev.send_recv(CCProtocolPacker.sign_transaction(ll, sha))

    with pytest.raises(CCProtoError):
        done = None
        while done == None:
            time.sleep(0.050)
            done = dev.send_recv(CCProtocolPacker.get_signed_txn(), timeout=None)


@pytest.mark.parametrize('fn', [
	'data/2-of-2.psbt',
	'data/dup_keys.psbt',
	'data/filled_scriptsig.psbt',
	'data/one-p2pkh-in.psbt',
	'data/p2pkh+p2sh+outs.psbt',
	'data/p2pkh-in-scriptsig.psbt',
	'data/p2pkh-p2sh-p2wpkh.psbt',
	'data/worked-1.psbt',
	'data/worked-2.psbt',
	'data/worked-unsigned.psbt',
	'data/worked-4.psbt',
	'data/worked-5.psbt',
	'data/worked-combined.psbt',
	'data/worked-7.psbt',
])
def test_psbt_proxy_parsing(fn, sim_execfile, sim_exec):
    # unit test: parsing by the psbt proxy object

    sim_exec('import main; main.FILENAME = %r; ' % ('../../testing/'+fn))
    rv = sim_execfile('devtest/unit_psbt.py')
    assert not rv, rv

    rb = '../unix/work/readback.psbt'

    oo = BasicPSBT().parse(open(fn, 'rb').read())
    rb = BasicPSBT().parse(open(rb, 'rb').read())
    assert oo == rb


@pytest.mark.parametrize('num_out', [1, 10,11, 250])
@pytest.mark.parametrize('num_in', [1, 10, 20])
@pytest.mark.parametrize('segwit', [True, False])
@pytest.mark.parametrize('out_style', ADDR_STYLES)
def test_io_size(request, decode_with_bitcoind, fake_txn,
                    start_sign, end_sign, dev, segwit, out_style, 
                    num_out, num_in, accept=True):

    # try a bunch of different bigger sized txns
    # - important to test on real device, due to it's limited memory
    # - cmdline: "pytest test_sign.py -k test_io_size --dev --manual -s --durations=50"
    # - simulator can do 400/400 but takes long time
    # - offical target: 20 inputs, 250 outputs (see docs/limitations.md)
    # - complete run on real hardware takes 1800.94 seconds = 30 minutes

    psbt = fake_txn(num_in, num_out, dev.master_xpub, segwit_in=segwit, outstyles=[out_style])

    open('debug/last.psbt', 'wb').write(psbt)

    start_sign(psbt, finalize=True)

    # on simulator, read screen
    try:
        cap_story = request.getfixturevalue('cap_story')
        time.sleep(.1)
        title, story = cap_story()
        assert 'OK TO SEND' in title
    except:
        cap_story = None

    signed = end_sign(accept, finalize=True)

    decoded = decode_with_bitcoind(signed)

    #print("Bitcoin code says:", end=''); pprint(decoded)

    if cap_story:
        # check we are showing right addresses
        shown = set()
        hidden = set()
        for i in decoded['vout']:
            dest = i['scriptPubKey']['addresses'][0]
            val = i['value']
            if dest in story:
                shown.add((val, dest))
                assert str(val) in story
            else:
                hidden.add((val, dest))

        # UI only shows 10 largest outputs if there are too many
        # - assuming no change outputs here
        MAX_VIZ = 10
        if num_out <= MAX_VIZ:
            assert len(shown) == num_out
            assert not hidden
        else:
            assert 'which total' in story
            assert len(shown) == MAX_VIZ
            assert len(hidden) >= 1
            assert len(shown) + len(hidden) == len(decoded['vout'])
            assert max(v for v,d in hidden) >= min(v for v,d in shown)
    
    
@pytest.mark.parametrize('num_ins', [ 2, 7, 15 ])
@pytest.mark.parametrize('segwit', [True, False])
def test_real_signing(fake_txn, try_sign, dev, num_ins, segwit, decode_with_bitcoind):
    # create a TXN using actual addresses that are correct for DUT
    xp = dev.master_xpub

    psbt = fake_txn(num_ins, 1, xp, segwit_in=segwit)
    open('debug/real-%d.psbt' % num_ins, 'wb').write(psbt)

    _, txn = try_sign(psbt, accept=True, finalize=True)

    #print('Signed; ' + B2A(txn))

    decoded = decode_with_bitcoind(txn)

    #pprint(decoded)

    assert len(decoded['vin']) == num_ins
    if segwit:
        assert all(x['txinwitness'] for x in decoded['vin'])

@pytest.mark.parametrize('we_finalize', [ False, True ])
@pytest.mark.parametrize('num_dests', [ 1, 10, 25 ])
@pytest.mark.bitcoind
def test_vs_bitcoind(match_key, check_against_bitcoind, bitcoind, start_sign, end_sign, we_finalize, num_dests):

    wallet_xfp = match_key()

    bal = bitcoind.getbalance()
    assert bal > 0, "need some play money; drink from a faucet"

    amt = round((bal/4)/num_dests, 6)

    args = {}

    for no in range(num_dests):
        dest = bitcoind.getrawchangeaddress()
        assert dest[0] in '2mn' or dest.startswith('tb1'), dest

        args[dest] = amt

    if 0:
        # old approach: fundraw + convert to psbt

        # working with hex strings here
        txn = bitcoind.createrawtransaction([], args)
        assert txn[0:2] == '02'
        #print(txn)

        resp = bitcoind.fundrawtransaction(txn)
        txn2 = resp['hex']
        fee = resp['fee']
        chg_pos = resp['changepos']
        #print(txn2)

        print("Sending %.8f XTN to %s (Change back in position: %d)" % (amt, dest, chg_pos))

        psbt = b64decode(bitcoind.converttopsbt(txn2, True))

    # use walletcreatefundedpsbt
    # - updated/validated against 0.17.1
    resp = bitcoind.walletcreatefundedpsbt([], args, 0, {
                'subtractFeeFromOutputs': list(range(num_dests)),
                'feeRate': 0.00001500}, True)

    if 0:
        # OMFG all this to reconstruct the rpc command!
        import json, decimal
        def EncodeDecimal(o):
            if isinstance(o, decimal.Decimal):
                return float(round(o, 8))
            raise TypeError

        print('walletcreatefundedpsbt "[]" "[%s]" 0 {} true' % json.dumps(args,
                    default=EncodeDecimal).replace('"', '\\"'))

    psbt = b64decode(resp['psbt'])
    fee = resp['fee']
    chg_pos = resp['changepos']

    open('debug/vs.psbt', 'wb').write(psbt)

    # check some basics
    mine = BasicPSBT().parse(psbt)
    from struct import unpack_from
    for i in mine.inputs:
        got_xfp, = unpack_from('I', list(i.bip32_paths.values())[0])
        #assert hex(got_xfp) == hex(wallet_xfp), "wrong HD master key fingerprint"

        # see <https://github.com/bitcoin/bitcoin/issues/15884>
        if hex(got_xfp) != hex(wallet_xfp):
            raise pytest.xfail("wrong HD master key fingerprint")

    # pull out included txn
    txn2 = B2A(mine.txn)

    start_sign(psbt, finalize=we_finalize)

    # verify against how bitcoind reads it
    check_against_bitcoind(txn2, fee)

    signed = end_sign(accept=True)
    open('debug/vs-signed.psbt', 'wb').write(signed)

    if not we_finalize:
        b4 = BasicPSBT().parse(psbt)
        aft = BasicPSBT().parse(signed)
        assert b4 != aft, "signing didn't change anything?"

        open('debug/signed.psbt', 'wb').write(signed)
        resp = bitcoind.finalizepsbt(str(b64encode(signed), 'ascii'), True)

        #combined_psbt = b64decode(resp['psbt'])
        #open('debug/combined.psbt', 'wb').write(combined_psbt)

        assert resp['complete'] == True, "bitcoind wasn't able to finalize it"

        network = a2b_hex(resp['hex'])

        # assert resp['complete']
        #print("Final txn: %r" % network)
        open('debug/finalized-by-btcd.txn', 'wb').write(network)

        # try to send it
        txed = bitcoind.sendrawtransaction(B2A(network))
        print("Final txn hash: %r" % txed)

    else:
        assert signed[0:4] != b'psbt', "expecting raw bitcoin txn"
        #print("Final txn: %s" % B2A(signed))
        open('debug/finalized-by-cc.txn', 'wb').write(signed)

        txed = bitcoind.sendrawtransaction(B2A(signed))
        print("Final txn hash: %r" % txed)

def test_sign_example(set_master_key, sim_execfile, start_sign, end_sign):
    # use the private key given in BIP 174 and do similar signing
    # as the examples.

    # TODO fix this
    # - doesn't work anymore, because we won't sign a multisig we don't know the wallet details for
    raise pytest.skip('needs rework')
    
    exk = 'tprv8ZgxMBicQKsPd9TeAdPADNnSyH9SSUUbTVeFszDE23Ki6TBB5nCefAdHkK8Fm3qMQR6sHwA56zqRmKmxnHk37JkiFzvncDqoKmPWubu7hDF'
    set_master_key(exk)

    mk = BIP32Node.from_wallet_key(exk)

    psbt = a2b_hex(open('data/worked-unsigned.psbt', 'rb').read())

    start_sign(psbt)
    signed = end_sign(True)

    aft = BasicPSBT().parse(signed)
    expect = BasicPSBT().parse(open('data/worked-combined.psbt', 'rb').read())

    assert aft == expect

    #assert 'require subpaths to be spec' in str(ee)

def test_sign_p2sh_p2wpkh(match_key, start_sign, end_sign, bitcoind):
    # Check we can finalize p2sh_p2wpkh inputs right.

    # TODO fix this
    # - doesn't work anymore, because we won't sign a multisig we don't know the wallet details for
    raise pytest.skip('needs rework')

    wallet_xfp = match_key()

    fn = 'data/p2sh_p2wpkh.psbt'

    psbt = open(fn, 'rb').read()

    start_sign(psbt, finalize=True)
    signed = end_sign(accept=True)
    #signed = end_sign(None)
    open('debug/p2sh-signed.psbt', 'wb').write(signed)

    #print('my finalization: ' + B2A(signed))

    start_sign(psbt, finalize=False)
    signed_psbt = end_sign(accept=True)

    # use bitcoind to combine
    open('debug/signed.psbt', 'wb').write(signed_psbt)
    resp = bitcoind.finalizepsbt(str(b64encode(signed_psbt), 'ascii'), True)

    assert resp['complete'] == True, "bitcoind wasn't able to finalize it"
    network = a2b_hex(resp['hex'])

    #print('his finalization: ' + B2A(network))

    assert network == signed

def test_sign_p2sh_example(set_master_key, sim_execfile, start_sign, end_sign, decode_psbt_with_bitcoind, offer_ms_import, need_keypress, clear_ms):
    # Use the private key given in BIP 174 and do similar signing
    # as the examples.

    # PROBLEM: we can't handle this, since we don't allow same cosigner key to be used
    # more than once and that check happens after we decide we can sign an input, and yet
    # no way to provide the right set of keys needed since 4 in total, etc, etc.
    # - code below nearly works tho
    raise pytest.skip('difficult example')
    
    # expect xfp=4F6A0CD9
    exk = 'tprv8ZgxMBicQKsPd9TeAdPADNnSyH9SSUUbTVeFszDE23Ki6TBB5nCefAdHkK8Fm3qMQR6sHwA56zqRmKmxnHk37JkiFzvncDqoKmPWubu7hDF'
    set_master_key(exk)

    # Peeked at PSBT to know the full, deep hardened path we'll need.
    # in1: 0'/0'/0' and 0'/0'/1'
    # in2: 0'/0'/3' and 0'/0'/2'

    config = "name: p2sh-example\npolicy: 2 of 2\n\n"
    n1 = BIP32Node.from_hwif(exk).subkey_for_path("0'/0'").hwif()
    n2 = BIP32Node.from_hwif(exk).subkey_for_path("0'/0'").hwif()
    xfp = '4F6A0CD9'
    config += f'{xfp}: {n1}\n{xfp}: {n2}\n'

    clear_ms()
    offer_ms_import(config)
    time.sleep(.1)
    need_keypress('y')

    psbt = a2b_hex(open('data/worked-unsigned.psbt', 'rb').read())

    # PROBLEM: revised BIP174 has p2sh multisig cases which we don't support yet.
    # - it has two signatures from same key on same input
    # - that's a rare case and not worth supporting in the firmware
    # - but we can do it in two passes
    # - the MS wallet is also hard, since dup xfp (same actual key) ... altho can
    #   provide different subkeys

    start_sign(psbt)
    part_signed = end_sign(True)

    open('debug/ex-signed-part.psbt', 'wb').write(part_signed)

    b4 = BasicPSBT().parse(psbt)
    aft = BasicPSBT().parse(part_signed)
    assert b4 != aft, "(partial) signing didn't change anything?"

    # NOTE: cannot handle combining multisig txn yet, so cannot finalize on-device
    start_sign(part_signed, finalize=False)
    signed = end_sign(True, finalize=False)

    open('debug/ex-signed.psbt', 'wb').write(signed)
    aft2 = BasicPSBT().parse(signed)

    decode = decode_psbt_with_bitcoind(signed)
    pprint(decode)

    mx_expect = BasicPSBT().parse(a2b_hex(open('data/worked-combined.psbt', 'rb').read()))
    assert aft2 == mx_expect

    expect = a2b_hex(open('data/worked-combined.psbt', 'rb').read())
    decode_ex = decode_psbt_with_bitcoind(expect)

    # NOTE: because we are using RFC6979, the exact bytes of the signatures should match

    for i in range(2):
        assert decode['inputs'][i]['partial_signatures'] == \
                    decode_ex['inputs'][i]['partial_signatures']

    if 0:
        import json, decimal
        def EncodeDecimal(o):
            if isinstance(o, decimal.Decimal):
                return float(round(o, 8))
            raise TypeError
        json.dump(decode, open('debug/core-decode.json', 'wt'), indent=2, default=EncodeDecimal)

@pytest.mark.bitcoind
def test_change_case(start_sign, end_sign, check_against_bitcoind, cap_story):
    # is change shown/hidden at right times. no fraud checks 

    # NOTE: out#1 is change:
    chg_addr = 'mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'

    psbt = open('data/example-change.psbt', 'rb').read()

    start_sign(psbt)

    time.sleep(.1)
    _, story = cap_story()
    assert chg_addr in story

    b4 = BasicPSBT().parse(psbt)
    check_against_bitcoind(B2A(b4.txn), Decimal('0.00000294'), change_outs=[1,])

    signed = end_sign(True)
    open('debug/chg-signed.psbt', 'wb').write(signed)

    # modify it: remove bip32 path
    b4.outputs[1].bip32_paths = {}
    with BytesIO() as fd:
        b4.serialize(fd)
        mod_psbt = fd.getvalue()

    start_sign(mod_psbt)

    time.sleep(.1)
    _, story = cap_story()

    # no change expected (they are outputs)
    assert 'Change back' not in story

    check_against_bitcoind(B2A(b4.txn), Decimal('0.00000294'), change_outs=[])

    signed2 = end_sign(True)
    open('debug/chg-signed2.psbt', 'wb').write(signed)
    aft = BasicPSBT().parse(signed)
    aft2 = BasicPSBT().parse(signed2)
    assert aft.txn == aft2.txn

@pytest.mark.parametrize('case', [ 1, 2])
@pytest.mark.bitcoind
def test_change_fraud_path(start_sign, end_sign, case, check_against_bitcoind, cap_story):
    # fraud: BIP32 path of output doesn't lead to pubkey indicated

    # NOTE: out#1 is change:
    chg_addr = 'mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'

    psbt = open('data/example-change.psbt', 'rb').read()
    b4 = BasicPSBT().parse(psbt)

    (pubkey, path), = b4.outputs[1].bip32_paths.items()
    skp = bytearray(b4.outputs[1].bip32_paths[pubkey])
    if case == 1:
        # change subkey
        skp[-2] ^= 0x01
    elif case == 2:
        # change xfp
        skp[0] ^= 0x01

    b4.outputs[1].bip32_paths[pubkey] = bytes(skp)

    with BytesIO() as fd:
        b4.serialize(fd)
        mod_psbt = fd.getvalue()

    open('debug/mod-%d.psbt' % case, 'wb').write(mod_psbt)

    if case == 1:
        start_sign(mod_psbt)
        with pytest.raises(CCProtoError) as ee:
            signed = end_sign(True)
        assert 'BIP32 path' in str(ee)
    elif case == 2:
        # will not consider it a change output, but not an error either
        start_sign(mod_psbt)
        check_against_bitcoind(B2A(b4.txn), Decimal('0.00000294'), change_outs=[])

        time.sleep(.1)
        _, story = cap_story()
        assert chg_addr in story
        assert 'Change back:' not in story

        signed = end_sign(True)

@pytest.mark.bitcoind
def test_change_fraud_addr(start_sign, end_sign, check_against_bitcoind, cap_story):
    # fraud: BIP32 path of output doesn't match TXO address
    from pycoin.tx.Tx import Tx
    from pycoin.tx.TxOut import TxOut

    # NOTE: out#1 is change:
    #chg_addr = 'mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'

    psbt = open('data/example-change.psbt', 'rb').read()
    b4 = BasicPSBT().parse(psbt)

    # tweak output addr to garbage
    t = Tx.parse(BytesIO(b4.txn))
    chg = t.txs_out[1]          # pycoin.tx.TxOut.TxOut
    b = bytearray(chg.script)
    b[-5] ^= 0x55
    chg.script = bytes(b)

    b4.txn = t.as_bin()

    with BytesIO() as fd:
        b4.serialize(fd)
        mod_psbt = fd.getvalue()

    open('debug/mod-addr.psbt', 'wb').write(mod_psbt)

    start_sign(mod_psbt)
    with pytest.raises(CCProtoError) as ee:
        signed = end_sign(True)
    assert 'Change output is fraud' in str(ee)


@pytest.mark.parametrize('case', [ 'p2wpkh', 'p2sh'])
@pytest.mark.bitcoind
def test_change_p2sh_p2wpkh(start_sign, end_sign, check_against_bitcoind, cap_story, case):
    # not fraud: output address encoded in various equiv forms
    from pycoin.tx.Tx import Tx
    from pycoin.tx.TxOut import TxOut

    # NOTE: out#1 is change:
    #chg_addr = 'mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'

    psbt = open('data/example-change.psbt', 'rb').read()
    b4 = BasicPSBT().parse(psbt)

    t = Tx.parse(BytesIO(b4.txn))

    pkh = t.txs_out[1].hash160()

    if case == 'p2wpkh':
        t.txs_out[1].script = bytes([0, 20]) + bytes(pkh)

        from bech32 import encode
        expect_addr = encode('tb', 0, pkh)

    elif case == 'p2sh':

        spk = bytes([0xa9, 0x14]) + pkh + bytes([0x87])

        b4.outputs[1].redeem_script = bytes([0, 20]) + bytes(pkh)
        t.txs_out[1].script = spk

        expect_addr = t.txs_out[1].address('XTN')

    b4.txn = t.as_bin()

    with BytesIO() as fd:
        b4.serialize(fd)
        mod_psbt = fd.getvalue()

    open('debug/mod-%s.psbt' % case, 'wb').write(mod_psbt)

    start_sign(mod_psbt)

    time.sleep(.1)
    _, story = cap_story()

    check_against_bitcoind(B2A(b4.txn), Decimal('0.00000294'), change_outs=[1,],
            dests=[(1, expect_addr)])

    #print(story)
    assert expect_addr in story
    assert parse_change_back(story) == (Decimal('1.09997082'), [expect_addr])

    signed = end_sign(True)

def test_sign_multisig_partial_fail(start_sign, end_sign):

    # file from AChow, via slack: a partially signed multisig setup (which we can't handle)
    #fn = 'data/multisig-single.psbt'
    fn = 'data/multisig-single-unsigned.psbt'
    from base64 import b64decode

    psbt = b64decode(open(fn, 'rb').read())

    with pytest.raises(CCProtoError) as ee:
        start_sign(psbt, finalize=True)
        signed = end_sign(accept=True)

    assert 'None of the keys involved' in str(ee)

def test_sign_wutxo(start_sign, set_seed_words, end_sign, cap_story, sim_exec, sim_execfile):

    # Example from SomberNight: we can sign it, but signature won't be accepted by
    # network because the PSBT lies about the UTXO amount and tries to give away to miners,
    # as overly-large fee.

    set_seed_words('fault lava rice chest uncle exclude power tornado catalog stool'
                    ' swear rival sun aspect oyster deer pepper exchange scrap toward'
                    ' mix second world shaft')

    in_psbt = a2b_hex(open('data/snight-example.psbt', 'rb').read()[:-1])

    for fin in (False, True):
        start_sign(in_psbt, finalize=fin)

        time.sleep(.1)
        _, story = cap_story()

        #print(story)

        assert 'Network fee:\n0.00000500 XTN' in story

        # check we understood it right
        ex = dict(  had_witness=False, num_inputs=1, num_outputs=1, sw_inputs=[True], 
                    miner_fee=500, warnings_expected=0,
                    lock_time=1442308, total_value_out=99500,
                    total_value_in=100000)

        rv= sim_exec('import main; main.EXPECT = %r; ' % ex)
        if rv: pytest.fail(rv)
        rv = sim_execfile('devtest/check_decode.py')
        if rv: pytest.fail(rv)

        signed = end_sign(True, finalize=fin)

        open('debug/sn-signed.'+ ('txn' if fin else 'psbt'), 'wt').write(B2A(signed))

@pytest.mark.parametrize('fee_max', [ 10, 25, 50])
@pytest.mark.parametrize('under', [ False, True])
def test_network_fee_amts(fee_max, under, fake_txn, try_sign, start_sign, dev, settings_set, sim_exec, cap_story):

    settings_set('fee_limit', fee_max)

    # creat a txn with single 1BTC input, and one output, equal to 1BTC-fee
    target = (fee_max - 2) if under else fee_max
    outval = int(1E8 / ((target/100.) + 1.))

    psbt = fake_txn(1, 1, dev.master_xpub, fee=None, outvals=[outval])

    open('debug/fee.psbt', 'wb').write(psbt)

    if not under:
        with pytest.raises(CCProtoError) as ee:
            try_sign(psbt, False)
        msg = ee.value.args[0]
        assert 'Network fee bigger than' in msg
        assert ('than %d%% of total' % target) in msg
    else:
        start_sign(psbt, False)
        time.sleep(.1)
        _, story = cap_story()

        assert 'warning below' in story
        assert 'Big Fee' in story
        assert 'more than 5% of total' in story

    settings_set('fee_limit', 10)

def test_network_fee_unlimited(fake_txn, start_sign, end_sign, dev, settings_set, cap_story):

    settings_set('fee_limit', -1)

    # creat a txn with single 1BTC input, and tiny one output; the rest is fee
    outval = 100

    psbt = fake_txn(1, 1, dev.master_xpub, fee=None, outvals=[outval])

    open('debug/fee-un.psbt', 'wb').write(psbt)

    # should be able to sign, but get warning
    start_sign(psbt, False)

    time.sleep(.1)
    _, story = cap_story()

    #print(story)

    assert 'warning below' in story
    assert 'Big Fee' in story
    assert 'more than 5% of total' in story

    settings_set('fee_limit', 10)

@pytest.mark.parametrize('num_outs', [ 2, 7, 15 ])
@pytest.mark.parametrize('act_outs', [ 2, 1, -1])
@pytest.mark.parametrize('segwit', [True, False])
@pytest.mark.parametrize('add_xpub', [True, False])
@pytest.mark.parametrize('out_style', ADDR_STYLES_SINGLE)
@pytest.mark.parametrize('visualized', [0, STXN_VISUALIZE, STXN_VISUALIZE|STXN_SIGNED])
def test_change_outs(fake_txn, start_sign, end_sign, cap_story, dev, num_outs, master_xpub,
                        act_outs, segwit, out_style, visualized, add_xpub, num_ins=3):
    # create a TXN which has change outputs, which shouldn't be shown to user, and also not fail.
    xp = dev.master_xpub

    couts = num_outs if act_outs == -1 else num_ins-act_outs
    psbt = fake_txn(num_ins, num_outs, xp, segwit_in=segwit,
                        outstyles=[out_style], change_outputs=range(couts), add_xpub=add_xpub)

    open('debug/change.psbt', 'wb').write(psbt)

    # should be able to sign, but get warning
    if not visualized:
        start_sign(psbt, False)

        time.sleep(.1)
        title, story = cap_story()
        print(repr(story))

        assert title == "OK TO SEND?"
    else:
        # use new feature to have Coldcard return the 'visualization' of transaction
        start_sign(psbt, False, stxn_flags=visualized)
        story = end_sign(accept=None, expect_txn=False)

        story = story.decode('ascii')

        if (visualized & STXN_SIGNED):
            # last line should be signature, using 'm' over the rest
            from pycoin.contrib.msg_signing import verify_message
            from pycoin.key.BIP32Node import BIP32Node

            #def verify_message(key_or_address, signature, message=None, msg_hash=None, netcode=None):

            assert story[-1] == '\n'
            last_nl = story[:-1].rindex('\n')
            msg, sig = story[0:last_nl+1], story[last_nl:]
            wallet = BIP32Node.from_wallet_key(master_xpub)
            assert verify_message(wallet, sig, message=msg) == True
            story = msg

    assert 'Network fee' in story

    if couts < num_outs:
        assert '- to address -' in story
    else:
        assert 'Consolidating' in story

    if couts == 1:
        assert "- to address -" in story
    else:
        assert "- to addresses -" in story

    val, addrs = parse_change_back(story)
    assert val > 0          # hard to calc here
    assert len(addrs) == couts
    if out_style == 'p2pkh':
        assert all((i[0] in 'mn') for i in addrs)
    elif out_style == 'p2wpkh':
        assert set(i[0:4] for i in addrs) == {'tb1q'}
    elif out_style == 'p2wpkh-p2sh':
        assert set(i[0] for i in addrs) == {'2'}

def KEEP_test_random_psbt(try_sign, sim_exec, fname="data/   .psbt"):
    # allow almost any PSBT to run on simulator, at least up until wrong pubkeys detected
    # - detects expected XFP and changes to match
    # - good for debug of random psbt
    oo = BasicPSBT().parse(open(fname, 'rb').read())
    paths = []
    for i in oo.inputs:
         paths.extend(i.bip32_paths.values())

    used = set(i[0:4] for i in paths)
    assert len(used) == 1, "multiple key fingerprints in inputs, can only handle 1"
    import struct
    need_xfp, = struct.unpack("<I", used.pop())

    sim_exec('from main import settings; settings.set("xfp", 0x%x);' % need_xfp)


    with pytest.raises(CCProtoError) as ee:
        orig, result = try_sign(fname, accept=True)

    msg = ee.value.args[0]
    assert 'Signing failed late' in msg
    assert 'led to wrong pubkey for input' in msg


@pytest.mark.parametrize('num_dests', [ 1, 10, 25 ])
@pytest.mark.bitcoind
def test_finalization_vs_bitcoind(match_key, check_against_bitcoind, bitcoind, start_sign, end_sign, num_dests):
    # Compare how we finalize vs bitcoind ... should be exactly the same txn

    wallet_xfp = match_key()

    bal = bitcoind.getbalance()
    assert bal > 0, "need some play money; drink from a faucet"

    amt = round((bal/4)/num_dests, 6)

    args = {}

    for no in range(num_dests):
        dest = bitcoind.getrawchangeaddress()
        assert dest[0] in '2mn' or dest.startswith('tb1'), dest

        args[dest] = amt

    # use walletcreatefundedpsbt
    # - updated/validated against 0.17.1
    resp = bitcoind.walletcreatefundedpsbt([], args, 0, {
                'subtractFeeFromOutputs': list(range(num_dests)),
                'feeRate': 0.00001500}, True)

    psbt = b64decode(resp['psbt'])
    fee = resp['fee']
    chg_pos = resp['changepos']

    open('debug/vs.psbt', 'wb').write(psbt)

    # check some basics
    mine = BasicPSBT().parse(psbt)
    from struct import unpack_from
    for i in mine.inputs:
        got_xfp, = unpack_from('I', list(i.bip32_paths.values())[0])
        #assert hex(got_xfp) == hex(wallet_xfp), "wrong HD master key fingerprint"

        # see <https://github.com/bitcoin/bitcoin/issues/15884>
        if hex(got_xfp) != hex(wallet_xfp):
            raise pytest.xfail("wrong HD master key fingerprint")

    # pull out included txn
    txn2 = B2A(mine.txn)

    start_sign(psbt, finalize=True)

    # verify against how bitcoind reads it
    check_against_bitcoind(txn2, fee)

    signed_final = end_sign(accept=True)
    assert signed_final[0:4] != b'psbt', "expecting raw bitcoin txn"
    open('debug/finalized-by-ckcc.txn', 'wt').write(B2A(signed_final))

    # Sign again, but don't finalize it.
    start_sign(psbt, finalize=False)
    signed = end_sign(accept=True)

    open('debug/vs-signed-unfin.psbt', 'wb').write(signed)

    # Use bitcoind to finalize it this time.
    resp = bitcoind.finalizepsbt(str(b64encode(signed), 'ascii'), True)
    assert resp['complete'] == True, "bitcoind wasn't able to finalize it"

    network = a2b_hex(resp['hex'])

    # assert resp['complete']
    #print("Final txn: %r" % network)
    open('debug/finalized-by-btcd.txn', 'wt').write(B2A(network))

    assert network == signed_final, "Finalized differently"

    # try to send it
    txed = bitcoind.sendrawtransaction(B2A(network))
    print("Final txn hash: %r" % txed)


# Correct change path is: (m=4369050F)/44'/1'/0'/1/5
@pytest.mark.parametrize('try_path,expect', [
    ("44'/1'/0'/1/40000", 'last component beyond'),
    ("44'/1'/0'/1/405", 'last component beyond'),
    ("44'/1'/0'/1'/5", 'hardening'),
    ("44'/1'/0'/1/5'", 'hardening'),
    ("44'/1/0'/1/5'", 'hardening'),
    ("45'/1'/0'/1/5", 'diff path prefix'),
    ("44'/2'/0'/1/5", 'diff path prefix'),
    ("44'/1'/1'/1/5", 'diff path prefix'),
    ("44'/1'/0'/3000/5", '2nd last component'),
    ("44'/1'/0'/3/5", '2nd last component'),
])
def test_change_troublesome(start_sign, cap_story, try_path, expect):
    from struct import pack

    # NOTE: out#1 is change:
    # addr = 'mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'
    # path = (m=4369050F)/44'/1'/0'/1/5
    # pubkey = 03c80814536f8e801859fc7c2e5129895b261153f519d4f3418ffb322884a7d7e1

    psbt = open('data/example-change.psbt', 'rb').read()
    b4 = BasicPSBT().parse(psbt)

    if 0:
        #from pycoin.tx.Tx import Tx
        #from pycoin.tx.TxOut import TxOut
        # tweak output addr to garbage
        t = Tx.parse(BytesIO(b4.txn))
        chg = t.txs_out[1]          # pycoin.tx.TxOut.TxOut
        b = bytearray(chg.script)
        b[-5] ^= 0x55
        chg.script = bytes(b)

        b4.txn = t.as_bin()

    pubkey = a2b_hex('03c80814536f8e801859fc7c2e5129895b261153f519d4f3418ffb322884a7d7e1')
    path = [int(p) if ("'" not in p) else 0x80000000+int(p[:-1]) 
                        for p in try_path.split('/')]
    bin_path = b4.outputs[1].bip32_paths[pubkey][0:4] \
                + b''.join(pack('<I', i) for i in path)
    b4.outputs[1].bip32_paths[pubkey] = bin_path

    with BytesIO() as fd:
        b4.serialize(fd)
        mod_psbt = fd.getvalue()

    open('debug/troublesome.psbt', 'wb').write(mod_psbt)

    start_sign(mod_psbt)
    time.sleep(0.1)
    title, story = cap_story()
    assert 'OK TO SEND' in title
    assert '(1 warning below)' in story, "no warning shown"

    assert expect in story, story

    assert parse_change_back(story) == (Decimal('1.09997082'), ['mvBGHpVtTyjmcfSsy6f715nbTGvwgbgbwo'])

def test_bip143_attack(try_sign, sim_exec, set_xfp, settings_set, settings_get):
    # cleanup prev runs
    sim_exec('import history; history.OutptValueCache.clear()')

    # hand-modified transactions from Andrew Chow
    set_xfp('D1A226A9')
    mod1 = b64decode(open('data/b143a_mod1.psbt').read())
    mod2 = b64decode(open('data/b143a_mod2.psbt').read())

    orig, result = try_sign(mod1, accept=False)

    # after seeing first one, should raise an error on second one
    with pytest.raises(CCProtoError) as ee:
        orig, result = try_sign(mod2, accept=False)

    assert 'but PSBT claims 15 XTN' in str(ee), ee

    assert len(settings_get('ovc')) == 2
    sim_exec('import history; history.OutptValueCache.clear()')

    # try in opposite order, should also trigger
    orig, result = try_sign(mod2, accept=False)
    with pytest.raises(CCProtoError) as ee:
        orig, result = try_sign(mod1, accept=False)

    assert 'but PSBT claims' in str(ee), ee
    assert 'Expected 15 but' in str(ee)

def spend_outputs(funding_psbt, finalized_txn, tweaker=None):
    # take details from PSBT that created a finalized txn (also provided)
    # and build a new PSBT that spends those change outputs.
    from pycoin.tx.Tx import Tx
    from pycoin.tx.TxOut import TxOut
    from pycoin.tx.TxIn import TxIn
    funding = Tx.from_bin(finalized_txn)
    b4 = BasicPSBT().parse(funding_psbt)

    # segwit change outputs only
    spendables = [(n,i) for n,i in enumerate(funding.tx_outs_as_spendable()) 
                        if i.script[0:2] == b'\x00\x14' and b4.outputs[n].bip32_paths]

    #spendables = list(reversed(spendables))
    random.shuffle(spendables)

    if tweaker:
        tweaker(spendables)

    nn = BasicPSBT()
    nn.inputs = [BasicPSBTInput(idx=i) for i in range(len(spendables))]
    nn.outputs = [BasicPSBTOutput(idx=0)]

    # copy input values from funding PSBT's output side
    for p_in, (f_out, sp) in zip(nn.inputs, [(b4.outputs[x], s) for x,s in spendables]):
        p_in.bip32_paths = f_out.bip32_paths
        p_in.witness_script = f_out.redeem_script
        with BytesIO() as fd:
            sp.stream(fd)
            p_in.witness_utxo = fd.getvalue()

    # build new txn: single output, no change, no miner fee
    act_scr = fake_dest_addr('p2wpkh')
    dest_out = TxOut(sum(s.coin_value for n,s in spendables), act_scr)

    txn = Tx(2, [s.tx_in() for _,s in spendables], [dest_out])

    # put unsigned TXN into PSBT
    with BytesIO() as b:
        txn.stream(b)
        nn.txn = b.getvalue()

    with BytesIO() as rv:
        nn.serialize(rv)
        raw = rv.getvalue()
    
    open('debug/spend_outs.psbt', 'wb').write(raw)

    return nn, raw

@pytest.mark.parametrize('num_utxo', [9, 100])
def test_bip143_attack_data_capture(num_utxo, try_sign, fake_txn, settings_set,
                                    settings_get, cap_story, sim_exec):

    # make a txn, capture the outputs of that as inputs for another txn

    # cleanup prev runs
    sim_exec('import history; history.OutptValueCache.clear()')

    psbt = fake_txn(1, num_utxo+3, segwit_in=True, change_outputs=range(num_utxo+2),
                        outstyles=(['p2wpkh']*num_utxo) + ['p2wpkh-p2sh', 'p2pkh'])
    _, txn = try_sign(psbt, accept=True, finalize=True)

    time.sleep(.1)
    title, story = cap_story()
    assert 'TXID' in title, story
    txid = story.strip()

    # compare to PyCoin
    from pycoin.tx.Tx import Tx
    t = Tx.from_bin(txn)
    assert t.id() == txid

    # expect all of new "change outputs" to be recorded (none of the non-segwit change tho)
    # plus the one input we "revealed"
    after1 = settings_get('ovc')
    assert len(after1) == min(30, num_utxo + 1)

    all_utxo = int(sim_exec(
        'import history; RV.write(str(len(history.OutptValueCache.runtime_cache)));'))
    assert all_utxo == num_utxo+1

    # build a new PSBT based on those change outputs
    psbt2, raw = spend_outputs(psbt, txn)

    # try to sign that ... should work fine
    try_sign(raw, accept=True, finalize=True)
    time.sleep(.1)

    # should not affect stored data, because those values already cached
    assert settings_get('ovc') == after1

    # any tweaks to input side's values should fail.
    for amt in [int(1E6), 1]:
        def value_tweak(spendables):
            assert len(spendables) > 2
            spendables[0][1].coin_value += amt

        psbt3, raw = spend_outputs(psbt, txn, tweaker=value_tweak)
        with pytest.raises(CCProtoError) as ee:
            orig, result = try_sign(raw, accept=True, finalize=True)

        assert 'but PSBT claims' in str(ee), ee


@pytest.mark.parametrize('segwit', [False, True])
@pytest.mark.parametrize('num_ins', [1, 17])
def test_txid_calc(num_ins, fake_txn, try_sign, dev, segwit, decode_with_bitcoind, cap_story):
    # create a TXN using actual addresses that are correct for DUT
    xp = dev.master_xpub

    psbt = fake_txn(num_ins, 1, xp, segwit_in=segwit)

    _, txn = try_sign(psbt, accept=True, finalize=True)

    #print('Signed; ' + B2A(txn))

    time.sleep(.1)
    title, story = cap_story()
    assert '0' in story
    assert 'TXID' in title, story
    txid = story.strip()

    if 1:
        # compare to PyCoin
        from pycoin.tx.Tx import Tx
        t = Tx.from_bin(txn)
        assert t.id() == txid

    if 1:
        # compare to bitcoin core
        decoded = decode_with_bitcoind(txn)
        pprint(decoded)

        assert len(decoded['vin']) == num_ins
        if segwit:
            assert all(x['txinwitness'] for x in decoded['vin'])

        assert decoded['txid'] == txid


# EOF
