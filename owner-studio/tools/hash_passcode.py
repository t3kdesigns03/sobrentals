#!/usr/bin/env python3
"""Rotate the Owner Studio passcode.
Usage: python3 hash_passcode.py "new passphrase here"
Prints the SALT (goes in wrangler.toml -> OWNER_SALT) and the HASH
(set with:  wrangler secret put OWNER_HASH ).
"""
import sys, os, base64, hashlib
if len(sys.argv) < 2:
    print('Usage: python3 hash_passcode.py "new passphrase"'); sys.exit(1)
passphrase = sys.argv[1]
salt = base64.b64encode(os.urandom(16)).decode()
h = hashlib.sha256((salt + passphrase).encode()).hexdigest()
print("OWNER_SALT (wrangler.toml [vars]):", salt)
print("OWNER_HASH (wrangler secret put OWNER_HASH):", h)
