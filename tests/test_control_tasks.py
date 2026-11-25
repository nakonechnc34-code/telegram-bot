import pytest
from routes.control import task_transition

def test_workflow():
    assert task_transition("new","start",False,True,"")=="in_progress"
    assert task_transition("in_progress","submit",False,True,"fixed")=="review"
    assert task_transition("review","approve",True,False,"")=="closed"
    assert task_transition("review","return",True,False,"redo")=="in_progress"

@pytest.mark.parametrize("args", [
    ("review","approve",False,True,""),
    ("review","approve",True,True,""),
    ("in_progress","submit",False,True,""),
    ("new","start",False,False,""),
    ("closed","return",True,False,"redo"),
])
def test_invalid_transition(args):
    with pytest.raises(ValueError):
        task_transition(*args)
