import logging
import json
import datetime as dt
from pathlib import Path
from abc import ABC, abstractmethod

import os
from AESCipher import AESCipher

log = logging.getLogger(__name__)


EXPIRES_ON_THRESHOLD = 1 * 60  # 1 minute


class Token(dict):
    """ A dict subclass with extra methods to resemble a token """

    @property
    def is_long_lived(self):
        """
        Checks whether this token has a refresh token
        :return bool: True if has a refresh_token
        """
        return 'refresh_token' in self

    @property
    def is_expired(self):
        """
        Checks whether this token is expired
        :return bool: True if the token is expired, False otherwise
        """
        return dt.datetime.now() > self.expiration_datetime

    @property
    def expiration_datetime(self):
        """
        Returns the expiration datetime
        :return datetime: The datetime this token expires
        """
        access_expires_at = self.access_expiration_datetime
        expires_on = access_expires_at - dt.timedelta(seconds=EXPIRES_ON_THRESHOLD)
        if self.is_long_lived:
            expires_on = expires_on + dt.timedelta(days=90)
        return expires_on

    @property
    def access_expiration_datetime(self):
        """
        Returns the token's access expiration datetime
        :return datetime: The datetime the token's access expires
        """
        expires_at = self.get('expires_at')
        if expires_at:
            return dt.datetime.fromtimestamp(expires_at)
        else:
            # consider the token expired, add 10 second buffer to current dt
            return dt.datetime.now() - dt.timedelta(seconds=10)

    @property
    def is_access_expired(self):
        """
        Returns whether or not the token's access is expired.
        :return bool: True if the token's access is expired, False otherwise
        """
        return dt.datetime.now() > self.access_expiration_datetime


class BaseTokenBackend(ABC):
    """ A base token storage class """

    serializer = json  # The default serializer is json
    token_constructor = Token  # the default token constructor

    def __init__(self):
        self._token = None

    @property
    def token(self):
        """ The stored Token dict """
        return self._token

    @token.setter
    def token(self, value):
        """ Setter to convert any token dict into Token instance """
        if value and not isinstance(value, Token):
            value = Token(value)
        self._token = value

    @abstractmethod
    def load_token(self):
        """ Abstract method that will retrieve the oauth token """
        raise NotImplementedError

    def get_token(self):
        """ Loads the token, stores it in the token property and returns it"""
        self.token = self.load_token()  # store the token in the 'token' property
        return self.token

    @abstractmethod
    def save_token(self):
        """ Abstract method that will save the oauth token """
        raise NotImplementedError

    def delete_token(self):
        """ Optional Abstract method to delete the token """
        raise NotImplementedError

    def check_token(self):
        """ Optional Abstract method to check for the token existence """
        raise NotImplementedError

    def should_refresh_token(self, con=None):
        """
        This method is intended to be implemented for environments
         where multiple Connection instances are running on paralel.

        This method should check if it's time to refresh the token or not.
        The chosen backend can store a flag somewhere to answer this question.
        This can avoid race conditions between different instances trying to
         refresh the token at once, when only one should make the refresh.

        > This is an example of how to achieve this:
        > 1) Along with the token store a Flag
        > 2) The first to see the Flag as True must transacionally update it
        >     to False. This method then returns True and therefore the
        >     connection will refresh the token.
        > 3) The save_token method should be rewrited to also update the flag
        >     back to True always.
        > 4) Meanwhile between steps 2 and 3, any other token backend checking
        >     for this method should get the flag with a False value.
        >     This method should then wait and check again the flag.
        >     This can be implemented as a call with an incremental backoff
        >     factor to avoid too many calls to the database.
        >     At a given point in time, the flag will return True.
        >     Then this method should load the token and finally return False
        >     signaling there is no need to refresh the token.

        If this returns True, then the Connection will refresh the token.
        If this returns False, then the Connection will NOT refresh the token.
        If this returns None, then this method already executed the refresh and therefore
         the Connection does not have to.

        By default this always returns True

        There is an example of this in the examples folder.

        :param Connection con: the connection that calls this method. This
         is passed because maybe the locking mechanism needs to refresh the
         token within the lock applied in this method.
        :rtype: bool or None
        :return: True if the Connection can refresh the token
                 False if the Connection should not refresh the token
                 None if the token was refreshed and therefore the
                  Connection should do nothing.
        """
        return True


class FileSystemTokenBackend(BaseTokenBackend):
    """ A token backend based on files on the filesystem """

    def __init__(self, token_path=None, token_filename=None):
        """
        Init Backend
        :param str or Path token_path: the path where to store the token
        :param str token_filename: the name of the token file
        """
        super().__init__()
        if not isinstance(token_path, Path):
            token_path = Path(token_path) if token_path else Path()

        if token_path.is_file():
            self.token_path = token_path
        else:
            token_filename = token_filename or 'o365_token.txt'
            self.token_path = token_path / token_filename

        self.cipher = AESCipher(os.environ['AES_KEY'])
        self.encrypt_token_path = self.token_path.parent / 'o365_token_encrypt.txt'

    def __repr__(self):
        return str(self.token_path)

    def load_token(self):
        """
        Retrieves the token from the File System
        :return dict or None: The token if exists, None otherwise
        """
        token = None
        if self.encrypt_token_path.exists():
            # with self.token_path.open('r') as token_file:
            #     token = self.token_constructor(self.serializer.load(token_file))
            with self.encrypt_token_path.open('rb') as encrypt_token_file:
                encrypted_json = encrypt_token_file.read()
                decrypted_json = self.cipher.decrypt(encrypted_json).decode("utf-8")
                token = self.token_constructor(self.serializer.loads(decrypted_json))
        return token

    def save_token(self):
        """
        Saves the token dict in the specified file
        :return bool: Success / Failure
        """
        if self.token is None:
            raise ValueError('You have to set the "token" first.')

        try:
            if not self.token_path.parent.exists():
                self.token_path.parent.mkdir(parents=True)
        except Exception as e:
            log.error('Token could not be saved: {}'.format(str(e)))
            return False

        # with self.token_path.open('w') as token_file:
        #     # 'indent = True' will make the file human readable
        #     self.serializer.dump(self.token, token_file, indent=True)
        with self.encrypt_token_path.open('wb') as encrypt_token_file:
            raw_json = self.serializer.dumps(self.token, indent=True)
            encrypted_json = self.cipher.encrypt(raw_json)
            encrypt_token_file.write(encrypted_json)

        return True

    def delete_token(self):
        """
        Deletes the token file
        :return bool: Success / Failure
        """
        if self.token_path.exists():
            self.token_path.unlink()
            return True
        return False

    def check_token(self):
        """
        Cheks if the token exists in the filesystem
        :return bool: True if exists, False otherwise
        """
        return self.token_path.exists()


class FirestoreBackend(BaseTokenBackend):
    """ A Google Firestore database backend to store tokens """

    def __init__(self, client, collection, doc_id, field_name='token'):
        """
        Init Backend
        :param firestore.Client client: the firestore Client instance
        :param str collection: the firestore collection where to store tokens (can be a field_path)
        :param str doc_id: # the key of the token document. Must be unique per-case.
        :param str field_name: the name of the field that stores the token in the document
        """
        super().__init__()
        self.client = client
        self.collection = collection
        self.doc_id = doc_id
        self.doc_ref = client.collection(collection).document(doc_id)
        self.field_name = field_name

    def __repr__(self):
        return 'Collection: {}. Doc Id: {}'.format(self.collection, self.doc_id)

    def load_token(self):
        """
        Retrieves the token from the store
        :return dict or None: The token if exists, None otherwise
        """
        token = None
        try:
            doc = self.doc_ref.get()
        except Exception as e:
            log.error('Token (collection: {}, doc_id: {}) '
                      'could not be retrieved from the backend: {}'
                      .format(self.collection, self.doc_id, str(e)))
            doc = None
        if doc and doc.exists:
            token_str = doc.get(self.field_name)
            if token_str:
                token = self.token_constructor(self.serializer.loads(token_str))
        return token

    def save_token(self):
        """
        Saves the token dict in the store
        :return bool: Success / Failure
        """
        if self.token is None:
            raise ValueError('You have to set the "token" first.')

        try:
            # set token will overwrite previous data
            self.doc_ref.set({
                self.field_name: self.serializer.dumps(self.token)
            })
        except Exception as e:
            log.error('Token could not be saved: {}'.format(str(e)))
            return False

        return True

    def delete_token(self):
        """
        Deletes the token from the store
        :return bool: Success / Failure
        """
        try:
            self.doc_ref.delete()
        except Exception as e:
            log.error('Could not delete the token (key: {}): {}'.format(self.doc_id, str(e)))
            return False
        return True

    def check_token(self):
        """
        Checks if the token exists
        :return bool: True if it exists on the store
        """
        try:
            doc = self.doc_ref.get()
        except Exception as e:
            log.error('Token (collection: {}, doc_id: {}) '
                      'could not be retrieved from the backend: {}'
                      .format(self.collection, self.doc_id, str(e)))
            doc = None
        return doc and doc.exists
