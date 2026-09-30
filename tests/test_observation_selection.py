from types import SimpleNamespace as NS
from app.services.evidence_processing import observation_frames


def test_visual_confirmation_included_and_calls_bounded():
    frames = [NS(path=str(i)) for i in range(20)]
    outcome = NS(extracted_frames=frames, frame_debug=[NS(path="7", engine="visual"), NS(path="8", engine="visual")])
    assert [f.path for f in observation_frames(outcome)] == ["8", "7", "0"]
    assert observation_frames(NS(extracted_frames=[], frame_debug=[])) == []
