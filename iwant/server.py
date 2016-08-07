from twisted.internet import reactor,defer,threads,endpoints
from twisted.internet.protocol import Factory
from twisted.protocols.basic import FileSender
from flashpointProtocol import FlashpointProtocol
from filehashIndex.FHIndex import FileHashIndexer
from communication.message import P2PMessage
from iwant.constants.server_event_constants import *

class backend(FlashpointProtocol):
    def __init__(self, factory):
        self.factory = factory
        self.message_codes = {
            HANDSHAKE : self._handshake,
            LIST_ALL_FILES : self._list_file,
            2 : self._load_file,
            3 : self._start_transfer,
            LEADER: self._update_leader,
            FILE_SYS_EVENT: self._filesystem_modified,
            HASH_DUMP : self._dump_data_from_peers
        }
        self.buff = ''
        self.delimiter = '#'

    def serviceMessage(self, data):
        req = P2PMessage(message=data)
        print 'GOT {0}'.format(req.key)
        try:
            self.message_codes[req.key]()
        except:
            self.message_codes[req.key](req.data)

    def _handshake(self):
        resMessage = P2PMessage(key=HANDSHAKE,data=[])
        self.sendLine(resMessage)

    def _list_file(self):
        if self.factory.state==1:
            resMessage = P2PMessage(key=LIST_ALL_FILES, data=self.factory.indexer.reduced_index())
            self.sendLine(resMessage)
        else:
            resMessage = P2PMessage(key=ERROR_LIST_ALL_FILES,data='File hashing incomplete')
            self.sendLine(resMessage)

    def _load_file(self,data):
        fhash = data[0]
        self.fileObj = self.factory.indexer.getFile(fhash)
        fsize = self.factory.indexer.hash_index[fhash].size
        ack_msg = P2PMessage(key=3,data=[fsize])
        self.sendLine(ack_msg)

    def _start_transfer(self):
        producer = FileSender()
        consumer = self.transport
        deferred = producer.beginFileTransfer(self.fileObj,consumer)
        deferred.addCallback(self._success,self._failure)

    def _success(self,data):
        print 'Successfully transfered file'

    def _failure(self,reason):
        print 'Failed {0}'.format(reason)

    def _update_leader(self, leader):
        self.factory.leader = leader
        print 'Leader {0}'.format(self.factory.book.leader)
        self.factory.gather_data_then_notify()

    def _filesystem_modified(self, data):
        print 'file system modified'
        self.factory.state = 1  # Ready
        self.factory.gather_data_then_notify()

    def _dump_data_from_peers(self, data):
        pass



class backendFactory(Factory):
    protocol = backend
    def __init__(self, folder, book):
        self.state = 0
        self.folder = folder
        self.book = book
        self.leader = None
        self.cached_data = None
        self.data_from_peers = None
        self.indexer = FileHashIndexer(self.folder)
        self.d = threads.deferToThread(self.indexer.index)
        self.d.addCallbacks(self._file_hash_success, self._file_hash_failure)

    def gather_data_then_notify(self):
        print 'gathering data'
        self.cached_data = {}
        with open('/var/log/iwant/.hindex') as f:
            hidx = f.read()
        with open('/var/log/iwant/.pindex') as f:
            pidx = f.read()
        self.cached_data['hidx'] = hidx
        self.cached_data['pidx'] = pidx
        self._notify_leader()

    def _notify_leader(self):
        from twisted.internet.protocol import Protocol, ClientFactory
        from twisted.internet import reactor

        class ServerLeaderProtocol(Protocol):
            def __init__(self, factory):
                self.factory = factory

            def connectionMade(self):
                update_msg = P2PMessage(key=HASH_DUMP, data=self.factory.dump)
                self.transport.write(str(update_msg))
                self.transport.loseConnection()

        class ServerLeaderFactory(ClientFactory):
            def __init__(self, dump):
                self.dump = dump

            def buildProtocol(self, addr):
                return ServerLeaderProtocol(self)

        factory = ServerLeaderFactory(dump=(self.book.uuidObj, self.cached_data))
        print 'state {0} \nleader {1}'.format(self.state, self.leader)
        if self.leader is not None and self.state==1:
            print self.leader[0], self.leader[1]
            reactor.connectTCP(self.leader[0], self.leader[1], factory)


    def _file_hash_success(self, data):
        self.state = 1  # Ready
        print 'Sucess baby'
        self.gather_data_then_notify()

    def _file_hash_failure(self, reason):
        print reason
        raise NotImplementedError

    def buildProtocol(self, addr):
        return backend(self)

    def connectionMade(self):
        print 'connection established'

if __name__ == '__main__':
    #folder = raw_input('Enter absolute path to share :')
    endpoints.serverFromString(reactor,'tcp:1235').listen(backendFactory('/home/nirvik/Pictures'))
    reactor.run()
