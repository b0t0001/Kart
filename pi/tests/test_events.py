import json
import uuid

from kartcv.events import Event


def test_event_json_shape():
    d = Event.new(cart_id="7", type="added", product_id="kirkland-parmesan", confidence=0.93, method="local",
                  label="Kirkland Parmigiano Reggiano", cameras=[0, 1], crops=["state/crops/x_cam0.jpg"]).to_json()
    assert set(d) == {"event_id", "cart_id", "type", "product_id", "confidence", "method", "label", "cameras", "crops",
                      "ts", "resolves_event_id"}
    assert uuid.UUID(d["event_id"]).version == 4 and d["ts"].endswith("Z")
    assert json.loads(json.dumps(d)) == d
