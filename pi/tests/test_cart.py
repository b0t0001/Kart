from kartcv.cart import CartMemory, View


def v(cam, x=10):
    return View(cam, (x, 20, 30, 40), [1.0, 0.0])


def test_add_remove_count_persist(tmp_path):
    p = tmp_path / "cart.json"
    m = CartMemory(p)
    a = m.add("red-box", "Red", {0: v(0), 1: v(1)})
    m.add("red-box", "Red", {0: v(0, 200)})
    b = m.add(None, "?", {1: v(1)})
    assert m.count("red-box") == 2 and len(m.views_in(0)) == 2 and len(m.views_in(1)) == 2
    m.remove(b.instance_id)
    m2 = CartMemory.load(p)
    assert list(m2.instances) == list(m.instances) and m2.instances[a.instance_id].views[1].box == (10, 20, 30, 40)


def test_update_shift_clear(tmp_path):
    m = CartMemory(tmp_path / "c.json")
    a = m.add("x", "X", {0: v(0)})
    m.update_views(a.instance_id, {1: v(1, 99)})
    m.shift_views(0, 5, -3)
    assert set(a.views) == {0, 1} and a.views[0].box == (15, 17, 30, 40)
    m.clear()
    assert CartMemory.load(tmp_path / "c.json").instances == {}
    assert CartMemory.load(tmp_path / "missing.json").instances == {}
