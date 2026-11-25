from routes.control import task_manager

def test_manager_requires_control_access():
    assert not task_manager({"permissions":{"control_manage":True}})
    assert not task_manager({"is_super_admin":True,"is_fired":True})

def test_explicit_management_permission():
    assert task_manager({"permissions":{"control_access":True,"control_manage":True}})
    assert not task_manager({"permissions":{"control_access":True,"control_manage":"true"}})
    assert not task_manager({"permissions":{"control_access":True}})
