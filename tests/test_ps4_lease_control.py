import pytest
from ports.ps4 import lease_control as control

@pytest.mark.parametrize('sequence',[1,99,4294967295])
@pytest.mark.parametrize('mode',range(4))
def test_protocol_roundtrip(sequence,mode):
    value=control.encode(sequence,mode)
    assert len(value)==22 and control.decode(value)==(sequence,mode)

@pytest.mark.parametrize('sequence',[0,-1,4294967296,True,1.0])
def test_sequence_invalid(sequence):
    with pytest.raises(ValueError): control.encode(sequence,1)

@pytest.mark.parametrize('value',[b'',b'ARFOXIA9:0000000000:1\n',b'ARFOXIA9:4294967296:1\n',
    b'ARFOXIA9:0000000001:4\n',b'ARFOXIA9:0000000001:1\r',b'ARFOXIA9:0000000x01:1\n',
    b'ARFOXIA9:0000000001:1\nEXTRA'])
def test_malformed_control_rejected(value):
    with pytest.raises(ValueError): control.decode(value)

class FTP:
    def __init__(self,files,events,*,corrupt=False): self.files,self.events,self.corrupt=files,events,corrupt
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def connect(self,host,port): self.events.append(('connect',host,port))
    def login(self): pass
    def cwd(self,path): assert path==control.REMOTE
    def nlst(self): return list(self.files)
    def retrbinary(self,cmd,callback,*args,**kwargs): callback(self.files[cmd[5:]])
    def storbinary(self,cmd,stream):
        self.events.append(('store',cmd)); self.files[cmd[5:]]=stream.read() if not self.corrupt else b'bad'
    def rename(self,source,destination):
        assert source==control.TEMP and destination==control.CONTROL
        self.events.append(('rename',source,destination)); self.files[destination]=self.files.pop(source)

def test_only_owner_control_is_atomically_replaced_after_readback():
    files={control.CONTROL:control.encode(10,1),'keep-log.txt':b'preserve'}; events=[]
    sequence=control.write_control('192.168.50.10','sit',ftp_factory=lambda **kwargs:FTP(files,events))
    assert sequence==11 and files[control.CONTROL]==control.encode(11,2)
    assert files['keep-log.txt']==b'preserve' and control.TEMP not in files
    assert events[-1][0]=='rename'

@pytest.mark.parametrize('files',[{control.TEMP:b'partial'},{control.CONTROL:b'unknown'}])
def test_interrupted_or_unknown_files_are_not_overwritten(files):
    before=files.copy(); events=[]
    with pytest.raises(ValueError):
        control.write_control('192.168.50.10','walk',ftp_factory=lambda **kwargs:FTP(files,events))
    assert files==before and not any(row[0]=='store' for row in events)

def test_bad_readback_never_replaces_existing_control():
    files={control.CONTROL:control.encode(1,1)}; events=[]
    with pytest.raises(ValueError,match='verification'):
        control.write_control('192.168.50.10','sit',ftp_factory=lambda **kwargs:FTP(files,events,corrupt=True))
    assert files[control.CONTROL]==control.encode(1,1)
    assert not any(row[0]=='rename' for row in events)

@pytest.mark.parametrize('host',['8.8.8.8','0.0.0.0','224.0.0.1','https://example.com','ps4.example'])
def test_non_private_or_ambiguous_host_refused_before_network(host):
    def factory(**kwargs): pytest.fail('No network expected')
    with pytest.raises(ValueError): control.write_control(host,'walk',ftp_factory=factory)

def test_controller_never_loads_payloads_or_plugins():
    import inspect
    source=inspect.getsource(control)
    for forbidden in ('9090','BinLoader','plugins.ini','sendall','subprocess','arfoxia_sdk'):
        assert forbidden not in source

@pytest.mark.parametrize('elapsed,mode',[(0,'walk'),(19.9,'walk'),(20,'sit'),(31.9,'sit'),
    (32,'idle'),(43.9,'idle'),(44,'walk'),(59.9,'walk'),(60,'stop'),(100,'stop')])
def test_demo_modes_are_finite_and_ordered(elapsed,mode):
    assert control.demo_mode(elapsed)==mode
