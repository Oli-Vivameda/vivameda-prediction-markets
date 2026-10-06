import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import configure_telegram as c, install

class Pairing(unittest.TestCase):
    def update(self,**changes):
        m={'text':'/start challenge','date':100,'chat':{'id':42,'type':'private'},
           'from':{'id':42,'is_bot':False}}
        m.update(changes);return [{'update_id':1,'message':m}]
    def test_correct_owner(self):self.assertTrue(c.paired(self.update(),42,'challenge',100))
    def test_wrong_owner(self):self.assertFalse(c.paired(self.update(),43,'challenge',100))
    def test_wrong_challenge(self):self.assertFalse(c.paired(self.update(),42,'wrong',100))
    def test_old_message(self):self.assertFalse(c.paired(self.update(date=99),42,'challenge',100))
    def test_group_refused(self):
        self.assertFalse(c.paired(self.update(chat={'id':42,'type':'group'}),42,'challenge',100))
    def test_sender_mismatch(self):
        self.assertFalse(c.paired(self.update(**{'from':{'id':43,'is_bot':False}}),42,'challenge',100))
    def test_same_crypto_bot_refused(self):
        with self.assertRaises(ValueError):c.verify_bot('1:abc','1:def',{}, {})
    def test_webhook_refused(self):
        with self.assertRaises(ValueError):c.verify_bot('2:abc','1:def',{'id':2,'is_bot':True,'username':'prediction_bot'},{'url':'https://example.org'})
    def test_identity_mismatch(self):
        with self.assertRaises(ValueError):c.verify_bot('2:abc','1:def',{'id':3,'is_bot':True,'username':'prediction_bot'}, {})
    def test_dedicated_bot(self):
        c.verify_bot('2:abc','1:def',{'id':2,'is_bot':True,'username':'prediction_bot'}, {})
    def test_manager_refused(self):
        with self.assertRaises(ValueError):c.verify_bot('2:abc','1:def',{'id':2,'is_bot':True,'username':'vivameda_boss_bot'}, {})
    def test_token_validation(self):
        for token in ('bad','2:abc/evil',None):
            with self.assertRaises(ValueError):c.bot_id(token)
    def test_installer_preserves_destination(self):
        self.assertEqual(install.CREDENTIAL_SOURCE,install.DEST/'telegram_credentials.json')
    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'link';p.symlink_to(Path(tmp)/'missing')
            with self.assertRaises(ValueError):c.safe_read(p)
    def test_confirmation_failure_restores_destination(self):
        calls=[];writes=[]
        def cmd(args):
            calls.append(args);return type('Result',(),{'stdout':'active'})()
        with patch.object(c,'safe_read',return_value={'bot_token':'1:old'}),patch.object(c,'atomic_write',side_effect=lambda *a:writes.append(a[1])):
            with self.assertRaises(ValueError):c.switch({'bot_token':'2:new'},1,lambda:False,cmd)
        self.assertEqual(writes,[{'bot_token':'2:new'},{'bot_token':'1:old'}])
        self.assertEqual(calls[-1],['systemctl','start',c.TIMER])
    def test_success_switch(self):
        writes=[]
        with patch.object(c,'safe_read',return_value={'bot_token':'1:old'}),patch.object(c,'atomic_write',side_effect=lambda *a:writes.append(a[1])):
            c.switch({'bot_token':'2:new'},1,lambda:True,lambda args:type('R',(),{'stdout':'active'})())
        self.assertEqual(writes,[{'bot_token':'2:new'}])

if __name__=='__main__':unittest.main()
