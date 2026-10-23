"""Remove exactly 38 retired CA fingerprints from effective OS/Python bundles.

References: OpenJDK blocked.certs.pem at commit85974eed594aa5a9e13a6a20713156ed8d9cd0ed
(SHA25623daaddff18ed3800bf38937b51cd91045777719baa19437d812afeb9b44b64e)
and certifi2026.10.23, compared with2026.7.22 and2026.10.19.
This changes CA data, not the versions of pip or its vendored packages.
"""
from __future__ import annotations
import hashlib,importlib.util,json,pathlib,re,ssl,subprocess
BLOCKED=frozenset(['0164d7ceae5bb909c272af151ff44b1177ae9b47d9424b94f1d9558c30934d19', '125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f', '14e6d2764a4b06701c6cbc376a253775f79c782fbcb6c0ee6f99de4ba1024add', '31c8fd37db9b56e708b03d1f01848b068c6da66f36fb5d82c008c6040fa3e133', '3946901f46b0071e90d78279e82fababca177231a704be72c5b0e8918566ea66', '42c4accd12c4f59597925e1a08a7a90102608543809308d50ec427e118ba1493', '432ec25f0d28de9006d97bf752f17bbb2cd41f669933fcb072d9a1148d0261f3', '450f1b421bb05c8609854884559c323319619e8b06b001ea2dcbb74a23aa3be2', '45a883f349aedfd5f3a649b5498ffb121712ba8b448f3f2a91dbc5a766fcddbe', '4b2460a466f95fd40113bcdcca2ceb29b3b093921de45474da7df48874c630b1', '4cbbf8256bc9888a8007b2f386940a2e394378b0d903cbb3863c5a6394b889ce', '4fee0163686ecbd65db968e7494f55d84b25486d438e9de558d629d28cd4d176', '579480aea166290bd3c643589e795fc0d0e54e86505d180f1dff99efd3199512', '5e83124d68d24e8e177e306df643d5ea99c5a94d6fc34b072f7544a1cabb7c7b', '5f1ded4dd590af74631290cf073b122a2aac6a1fa479778a0bd43579bd832699', '62b7f9868263f72f6911fc78ceaf72c1979158b7368bf648683bb2aa39b02e72', '7485b51c0ed192878fa1d2f948fb529ae1842cc5086c4b67f7be5b2039de9489', '76a45a496031e4dd2d7ed23e8f6ff97dbdea980baac8b0ba94d7edb551348645', '84112972b8e59d14560ae7e7119654474aad119990cf3722bfc1e3b91615e1fd', '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b', '8a1bd21661c60015065212cc98b1abb50dfd14c872a208e66bae890f25c448af', '98b896625c0c230adeec3eb2cf6aad5001ecf9156a68644e82374ce5833bc25b', '9e39de2881273acc225a149c72ba3e0f51424963669ab633ee1dc7df5db067b4', '9ed8f9b0e8e42a1656b8e1dd18f42ba42dc06fe52686173ba2fc70e756f207dc', 'a496e23ac0cab8155fc9b117b97eae368efcbb9041aec8804d5a308d2d01c2d8', 'a686fee577c88ab664d0787ecdfff035f4806f3de418dc9e4d516324fff02083', 'b8686723e415534bc0dbd16326f9486f85b0b0799bf6639334e61daae67f36cd', 'bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3', 'cb6e15165ac802e9b3f993f16c25d41f4e81c21ebde71ae1b012ac00bf9c7c3f', 'd24566bf315f4e597d6e381c87119fb4198f5e9e2607f5f4ab362ef7e2e7672f', 'd3a936e1a7775a45217c8296a1f22ac5631dcdec45594099e78eeebbedcba967', 'df21016b00fc54f9fe3bc8b039911bb216e9162fad2fd14d990ab96e951b49be', 'e7568fe6e12331f4fd7de61da4c7559d0f8eb192a218d4741a3ba75184333838', 'ec30c9c3065a06bb07dc5b1c6b497f370c1ca65c0f30c08e042ba6bcecc78f2c', 'f5b6f88f75d391a4b1eb336f9e201239fb6b1377db8cfa7b84736216e5afffd7', 'fc02fd48db92d4dce6f11679d38354cf750cfc7f584a520eb90bde80e241f2bd', 'fd9d5c2dbbd4995ab69b8d50c439d9527b00529199c2fd01b2174eb58f07021f', 'fdedb5bdfcb67411513a61aee5cb5b5d7c52af06028efc996cc1b05b1d6cea2b'])
PEM=re.compile(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',re.S)
def fingerprint(pem: bytes) -> str:
 return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode())).hexdigest()
def fingerprints(data: bytes) -> set[str]:
 return {fingerprint(pem)for pem in PEM.findall(data)}
def prune(data: bytes) -> bytes:
 return PEM.sub(lambda m:b''if fingerprint(m.group())in BLOCKED else m.group(),data)
def main() -> None:
 assert len(BLOCKED)==38
 removed=[]
 for root in ['/usr/share/ca-certificates','/usr/local/share/ca-certificates']:
  for path in pathlib.Path(root).rglob('*.crt'):
   hits=fingerprints(path.read_bytes())&BLOCKED
   if hits:
    assert len(fingerprints(path.read_bytes()))==1,'Refusing to delete a multi-certificate source file'
    path.unlink();removed.append({'store':'OS source','path':str(path),'fingerprints':sorted(hits)})
 subprocess.run(['update-ca-certificates','--fresh'],check=True,capture_output=True,text=True)
 bundles=list(pathlib.Path('/usr/local/lib').glob('python*/site-packages/pip/_vendor/certifi/cacert.pem'))
 if importlib.util.find_spec('certifi'):
  import certifi
  bundles.append(pathlib.Path(certifi.where()))
 for path in set(bundles):
  old=path.read_bytes();hits=fingerprints(old)&BLOCKED
  if hits:
   path.write_bytes(prune(old));removed.append({'store':'Python CA data','path':str(path),'fingerprints':sorted(hits)})
  assert not fingerprints(path.read_bytes())&BLOCKED
 ctx=ssl.create_default_context();assert ctx.verify_mode==ssl.CERT_REQUIRED and ctx.check_hostname
 assert not {hashlib.sha256(c).hexdigest()for c in ctx.get_ca_certs(binary_form=True)}&BLOCKED
 for path in pathlib.Path('/etc/ssl/certs').iterdir():
  if path.is_file():assert not fingerprints(path.read_bytes())&BLOCKED,str(path)
 print(json.dumps({'policy':'CA38','removed':removed,'tls_verification_required':True,'package_versions_changed':False}))
if __name__=='__main__':main()
