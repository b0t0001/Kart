import json

from kartcv.catalog import Catalog, Product, fetch_catalog, load_catalog


def test_load_store_json(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps({"products": [{"id": "kirkland-parmesan", "name": "Kirkland Parmigiano Reggiano",
        "price": 12.99, "section": "A4", "category": "cheese", "tags": [], "vision_hint": "wedge"}]}))
    cat = load_catalog(p)
    assert cat.ids() == ["kirkland-parmesan"] and cat.name("kirkland-parmesan") == "Kirkland Parmigiano Reggiano"
    assert "kirkland-parmesan | Kirkland Parmigiano Reggiano | wedge" in cat.prompt_lines()


def test_missing_hint_and_missing_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"products": [{"id": "a", "name": "A", "price": 1}]}')
    assert load_catalog(p).get("a").vision_hint == ""
    assert "kirkland-parmesan" in load_catalog(tmp_path / "nope.json").ids()


def test_fetch_catalog_from_supabase_and_failures():
    rows = [{"id": "new-thing", "name": "New Thing", "short_name": "New", "price": 3.5, "vision_hint": "green box"}]
    calls = []

    def get(url, headers):
        calls.append((url, headers))
        return 200, json.dumps(rows).encode()

    cat = fetch_catalog("https://x.supabase.co/", "k", get=get)
    assert cat.ids() == ["new-thing"] and cat.get("new-thing").vision_hint == "green box"
    # product_catalog only lists active products: undoing add_product delists rather than deletes
    assert calls[0][0] == "https://x.supabase.co/rest/v1/product_catalog?select=id,name,short_name,price,vision_hint"
    assert calls[0][1]["apikey"] == "k"

    def offline(url, headers):
        raise OSError("offline")

    assert fetch_catalog("https://x", "k", get=offline) is None
    assert fetch_catalog("https://x", "k", get=lambda u, h: (500, b"")) is None
    assert fetch_catalog("https://x", "k", get=lambda u, h: (200, b"[]")) is None
    assert fetch_catalog("https://x", "k", get=lambda u, h: (200, b"not json")) is None


def test_replace_with_is_seen_by_holders(tmp_path):
    cat = load_catalog(tmp_path / "nope.json")
    held = cat
    cat.replace_with(Catalog({"z": Product("z", "Z")}))
    assert held.ids() == ["z"]
