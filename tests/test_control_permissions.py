from routes.control import task_manager

def test_manager_requires_control_access():
    assert not task_manager({"permissions":{"control_manage":True}})
    assert not task_manager({"is_super_admin":True,"is_fired":True})

def test_explicit_management_permission():
    assert task_manager({"permissions":{"control_access":True,"control_manage":True}})
    assert not task_manager({"permissions":{"control_access":True,"control_manage":"true"}})
    assert not task_manager({"permissions":{"control_access":True}})

from routes.control import control_network_view, control_template_edit

def test_network_view_and_admin_edit():
    base={"permissions":{"control_access":True}}
    assert control_network_view(dict(base,position="Территориальный управляющий"))
    assert control_network_view({"permissions":{"control_access":True,"control_view_all":True}})
    assert not control_network_view(base)
    assert control_template_edit(dict(base,is_admin=True))
    assert not control_template_edit(base)
    us={"position":"УС","is_admin":True,"permissions":{"control_access":True,"control_view_all":True}}
    assert not control_network_view(us)
    assert not control_template_edit(us)
