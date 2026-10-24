from kartcv.catalog import Product
from kartcv.identify.cloud import CloudAnswer
from kartcv.identify.smoke import product_card, run_smoke


def test_product_card_is_a_camera_like_crop():
    img = product_card(Product("barilla-spaghetti", "Barilla Spaghetti", short_name="Spaghetti"), seed=1)
    assert img.ndim == 3 and img.shape[2] == 3 and 150 <= img.shape[0] <= 400 and 150 <= img.shape[1] <= 400


def test_run_smoke_scores_accuracy_and_latency():
    answers = {"a": CloudAnswer("a", 0.9, ""), "b": CloudAnswer("wrong", 0.9, ""), None: CloudAnswer(None, 0.2, "")}

    class Fake:
        def identify(self, crops):
            return answers[crops[0]]

    r = run_smoke(Fake(), [("a", ["a"]), ("b", ["b"]), (None, [None])])
    assert r["n"] == 3 and abs(r["accuracy"] - 2 / 3) < 1e-9 and len(r["rows"]) == 3
    assert r["rows"][1]["got"] == "wrong" and r["latency_s"]["max"] >= 0
