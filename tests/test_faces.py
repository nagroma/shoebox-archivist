import numpy as np

from backend import faces


def test_rotated_box_maps_back_to_the_original():
    img = np.zeros((400, 600, 3), dtype=np.uint8)
    for angle in faces.RETRY_ANGLES:
        turned, back = faces._rotate(img, angle)
        # where does original point (150, 100) land in the rotated image?
        fwd = np.vstack([faces.cv2.invertAffineTransform(back), [0, 0, 1]])
        x, y, _ = fwd @ [150, 100, 1]
        box = faces._upright_box((x - 20, y - 20, x + 20, y + 20), back)
        assert abs((box[0] + box[2]) / 2 - 150) < 1 and abs((box[1] + box[3]) / 2 - 100) < 1
        assert abs((box[2] - box[0]) - 40) < 1


def test_same_face():
    assert faces.same_face((0, 0, 10, 10), (2, 2, 12, 12))
    assert not faces.same_face((0, 0, 10, 10), (20, 20, 30, 30))
