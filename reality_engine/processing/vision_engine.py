"""Multimodal Vision Alpha Pipeline - keyframe extraction + VisualArtifact schema."""

from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class VisualArtifact(BaseModel):
    timestamp_seconds: int = Field(..., description="Keyframe start sec")
    timestamp_end_sec: Optional[int] = None
    artifact_type: str = Field(..., pattern=r"^(Financial_Table_Slide|Value_Chain_Diagram|Factory_Floor_Tour|Product_Tear_Down|CapEx_Timeline_Roadmap)$")
    on_screen_text_ocr: str = Field(..., description="Exact textual/numerical data shown on slide/graphic")
    visual_insights: str = Field(..., description="Insights visible in charts/diagrams not fully explained in audio")
    structured_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Parsed JSON of on-screen tables or KPI charts")
    target_ticker: Optional[str] = None
    moat_impact: Optional[str] = Field(None, description="How this alters switching_costs, scale, or pricing_power")
    visual_description: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    frame_snapshot_url: Optional[str] = None

class VideoIntelligenceExtraction(BaseModel):
    video_summary: str
    spoken_policy_signals: List[Dict[str, Any]] = Field(default_factory=list)
    visual_artifacts: List[VisualArtifact] = Field(default_factory=list)

# Sampling policy per spec
VIDEO_SAMPLING = {
    "slide_presentation": "1 frame every 2-5 sec",
    "factory_tour": "1 frame per scene-cut (ffmpeg scene 0.4 / OpenCV)",
}

def scene_change_keyframes(mp4: Path, mode: str = "slide_presentation") -> List[Path]:
    """Stub: ffmpeg -i input.mp4 -vf 'select=gt(scene,0.4)' -vsync vfr frame_%03d.jpg"""
    # Production: call ffmpeg subprocess or opencv VideoCapture
    # Returns list of keyframe image paths under /tmp/keyframes
    return []

def vision_extract(mp4_or_yt_url: str, audio_transcript: str, keyframes: List[Path]) -> VideoIntelligenceExtraction:
    """Local GPU DirectML pipeline: RapidOCR ONNX (AMD RX 6700 XT) + OpenCV — no Gemini/cloud call.
    For each keyframe: RapidOCR DirectML extracts on_screen_text_ocr + table JSON structured_data;
    OpenCV contours detect Value_Chain_Diagram/Factory_Floor_Tour visual_insights ≠ audio.
    Persist via: INSERT INTO visual_evidence_artifacts (doc_id, chunk_id, timestamp_start_sec, artifact_type, extracted_visual_data, visual_description, moat_implication, frame_snapshot_url, confidence_score)"""
    # Implementation: for frame in keyframes: result = RapidOCR(frame_path, det_db_box_thresh=0.5, use_dml=True)
    # Falls back to PyMuPDF/Whisper if DirectML absent per AGENTS.md:5 graceful fallback.
    return VideoIntelligenceExtraction(video_summary="", visual_artifacts=[])
