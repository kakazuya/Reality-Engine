"""
Agent Schemas Module
Defines structured data contracts for Scrip Alpha Theses, Market Breadth,
and Daily Alpha Reports with Pydantic and fallback dataclass/dict support.
"""

from __future__ import annotations

import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union, get_type_hints, get_origin, get_args

try:
    from pydantic import BaseModel as _PydanticBaseModel, Field as _PydanticField

    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


if _HAS_PYDANTIC:
    Field = _PydanticField

    class BaseSchema(_PydanticBaseModel):
        """Base schema with backward/forward compatibility methods."""

        model_config = {"extra": "ignore", "populate_by_name": True}

        def to_dict(self) -> Dict[str, Any]:
            if hasattr(self, "model_dump"):
                return self.model_dump()
            return self.dict()

        def to_json(self, indent: int = 2) -> str:
            if hasattr(self, "model_dump_json"):
                return self.model_dump_json(indent=indent)
            return json.dumps(self.to_dict(), indent=indent, default=str)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> Any:
            if hasattr(cls, "model_validate"):
                return cls.model_validate(data)
            return cls.parse_obj(data)

        @classmethod
        def from_json(cls, json_str: str) -> Any:
            if hasattr(cls, "model_validate_json"):
                return cls.model_validate_json(json_str)
            return cls.parse_raw(json_str)

else:
    def Field(default: Any = None, default_factory: Any = None, description: str = "", **kwargs) -> Any:
        return _FieldInfo(default=default, default_factory=default_factory, description=description, extra=kwargs)

    class _FieldInfo:
        def __init__(self, default: Any = None, default_factory: Any = None, description: str = "", extra: Optional[Dict[str, Any]] = None):
            self.default = default
            self.default_factory = default_factory
            self.description = description
            self.extra = extra or {}

    class BaseSchema:
        """Lightweight Pydantic-compatible fallback base schema."""

        def __init__(self, **values: Any):
            cls = self.__class__
            
            # Resolve type hints resolving string annotations if any
            try:
                # Build resolution namespace with globals of the class module
                module_globals = getattr(__import__(cls.__module__, fromlist=['__dict__']), '__dict__', globals())
                hints = get_type_hints(cls, module_globals)
            except Exception:
                hints = getattr(cls, "__annotations__", {})

            # Collect field definitions from class hierarchy
            field_defaults: Dict[str, Any] = {}
            for base in reversed(cls.__mro__):
                for k, v in getattr(base, "__dict__", {}).items():
                    if not k.startswith("_") and not callable(v):
                        field_defaults[k] = v

            for key, hint in hints.items():
                val = values.get(key)
                if val is None and key not in values:
                    default_obj = field_defaults.get(key)
                    if isinstance(default_obj, _FieldInfo):
                        if default_obj.default_factory is not None:
                            val = default_obj.default_factory()
                        else:
                            val = default_obj.default
                    else:
                        val = default_obj
                        if callable(val):
                            val = val()

                # Recursive instantiation for nested BaseSchema classes
                origin = get_origin(hint)
                args = get_args(hint)

                # If hint was unresolved string, check name
                if isinstance(hint, str):
                    if hint == "MarketBreadthSummary" and isinstance(val, dict):
                        val = globals().get("MarketBreadthSummary", dict)(**val)
                    elif "ScripAlphaThesis" in hint and isinstance(val, list):
                        target_cls = globals().get("ScripAlphaThesis")
                        if target_cls:
                            val = [target_cls(**item) if isinstance(item, dict) else item for item in val]
                elif isinstance(hint, type) and issubclass(hint, BaseSchema) and isinstance(val, dict):
                    val = hint(**val)
                elif (origin is list or origin is List) and isinstance(val, list):
                    item_type = args[0] if args else None
                    if isinstance(item_type, type) and issubclass(item_type, BaseSchema):
                        val = [item_type(**item) if isinstance(item, dict) else item for item in val]

                setattr(self, key, val)

            # Assign any extra attributes passed in values
            for k, v in values.items():
                if k not in hints:
                    setattr(self, k, v)

        def model_dump(self) -> Dict[str, Any]:
            res: Dict[str, Any] = {}
            for k, v in self.__dict__.items():
                if k.startswith("_"):
                    continue
                res[k] = self._serialize_value(v)
            return res

        def dict(self) -> Dict[str, Any]:
            return self.model_dump()

        def model_dump_json(self, indent: int = 2) -> str:
            return json.dumps(self.model_dump(), indent=indent, default=self._json_default)

        def json(self, indent: int = 2) -> str:
            return self.model_dump_json(indent=indent)

        def to_dict(self) -> Dict[str, Any]:
            return self.model_dump()

        def to_json(self, indent: int = 2) -> str:
            return self.model_dump_json(indent=indent)

        @classmethod
        def model_validate(cls, obj: Any) -> Any:
            if isinstance(obj, cls):
                return obj
            if isinstance(obj, dict):
                return cls(**obj)
            raise TypeError(f"Cannot validate {type(obj)} as {cls.__name__}")

        @classmethod
        def model_validate_json(cls, json_str: str) -> Any:
            data = json.loads(json_str)
            return cls.model_validate(data)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> Any:
            return cls.model_validate(data)

        @classmethod
        def from_json(cls, json_str: str) -> Any:
            return cls.model_validate_json(json_str)

        @classmethod
        def parse_obj(cls, obj: Any) -> Any:
            return cls.model_validate(obj)

        @classmethod
        def parse_raw(cls, json_str: str) -> Any:
            return cls.model_validate_json(json_str)

        @classmethod
        def _serialize_value(cls, val: Any) -> Any:
            if isinstance(val, BaseSchema):
                return val.model_dump()
            if isinstance(val, (list, tuple, set)):
                return [cls._serialize_value(item) for item in val]
            if isinstance(val, dict):
                return {k: cls._serialize_value(v) for k, v in val.items()}
            if isinstance(val, (datetime, date)):
                return val.isoformat()
            return val

        @staticmethod
        def _json_default(val: Any) -> Any:
            if isinstance(val, (datetime, date)):
                return val.isoformat()
            if hasattr(val, "model_dump"):
                return val.model_dump()
            if hasattr(val, "dict"):
                return val.dict()
            return str(val)

        def __repr__(self) -> str:
            attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items() if not k.startswith("_"))
            return f"{self.__class__.__name__}({attrs})"

        def __eq__(self, other: Any) -> bool:
            if isinstance(other, self.__class__):
                return self.model_dump() == other.model_dump()
            if isinstance(other, dict):
                return self.model_dump() == other
            return False


class ConvictionLevel:
    HIGH_CONVICTION = "HIGH_CONVICTION"
    MODERATE = "MODERATE"
    SPECULATIVE = "SPECULATIVE"


class MarketRegime:
    BULLISH = "BULLISH"
    ACCUMULATION = "ACCUMULATION"
    NEUTRAL = "NEUTRAL"
    VOLATILE = "VOLATILE"
    DISTRIBUTION = "DISTRIBUTION"


class ScripAlphaThesis(BaseSchema):
    """
    Comprehensive single-stock alpha thesis synthesizing technical flow,
    fundamental acceleration, causal macro drivers, and strict trade setups.
    """
    symbol: str = Field(..., description="NSE Ticker Symbol, e.g. HAL, KAYNES, TITAGARH")
    company_name: str = Field(..., description="Full legal name of the enterprise")
    composite_rank: int = Field(..., description="Rank in composite quant screener (1 to 5)")
    current_market_price: float = Field(..., description="Latest closing market price in INR")
    recommended_entry_range: str = Field(..., description="Target purchase range in INR, e.g. 'INR 5000.00 - INR 5080.00'")
    target_price: float = Field(..., description="Target exit price based on structural/fundamental valuation")
    stop_loss: float = Field(..., description="Strict stop loss level below structural support")
    risk_reward_ratio: float = Field(..., description="Calculated target profit to downside risk ratio (>= 2.5)")
    conviction_level: str = Field(
        default=ConvictionLevel.HIGH_CONVICTION,
        description="Confidence tier: 'HIGH_CONVICTION', 'MODERATE', or 'SPECULATIVE'"
    )
    techno_delivery_thesis: str = Field(
        ...,
        description="Vectorized assessment of delivery volume spike, 20D SMA, RSI momentum, and moving average alignment"
    )
    fundamental_thesis: str = Field(
        ...,
        description="Analysis of quarterly revenue/PAT growth, EBITDA margin delta (bps), ROCE quality, and solvency"
    )
    causal_macro_rationale: str = Field(
        ...,
        description="Causal graph transmission, policy tailwinds, supply chain resilience, and input pricing power"
    )
    key_catalysts: List[str] = Field(
        default_factory=list,
        description="List of key upcoming growth triggers, order book executions, or capacity commissioning"
    )
    key_risks: List[str] = Field(
        default_factory=list,
        description="List of key downside triggers, commodity sensitivities, or governance risks"
    )


class MarketBreadthSummary(BaseSchema):
    """
    Market-wide regime, sector rotation, and breadth snapshot.
    """
    advance_decline_ratio: float = Field(..., description="Ratio of advancing scrips to declining scrips")
    market_regime: str = Field(
        default=MarketRegime.NEUTRAL,
        description="Market regime: 'BULLISH', 'ACCUMULATION', 'NEUTRAL', 'VOLATILE', 'DISTRIBUTION'"
    )
    top_performing_sectors: List[str] = Field(
        default_factory=list,
        description="List of top outperforming sector indices"
    )
    vulnerable_sectors: List[str] = Field(
        default_factory=list,
        description="List of lagging or high-risk sector indices"
    )


class DailyAlphaReport(BaseSchema):
    """
    Master daily synthesized equity intelligence and alpha report.
    """
    date: str = Field(..., description="Report valuation date in YYYY-MM-DD format")
    universe: str = Field(default="NIFTY200", description="Screened universe name, e.g. 'NIFTY200' or 'ALL'")
    market_breadth: MarketBreadthSummary = Field(..., description="Market breadth and sector momentum summary")
    high_conviction_theses: List[ScripAlphaThesis] = Field(
        default_factory=list,
        description="Top high-conviction scrip theses with trade setups and causal rationale"
    )
    macro_shock_radar: Any = Field(
        default_factory=list,
        description="Active macroeconomic scenarios, commodity shocks, and causal transmission radar"
    )
    disqualified_solvency_count: int = Field(
        default=0,
        description="Number of candidate companies rejected by forensic solvency & pledge gates"
    )
    generated_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Timestamp of report synthesis"
    )


# --- Fundamental Reality Engine: Ripple DAG + Visual Alpha (PDF Architecture spec) ---
class RippleConsequence(BaseSchema):
    order_level: int = Field(..., ge=2, description="2 for second-order, 3 for third-order")
    target_type: str = Field(..., description="Sector|Industry|Company")
    target_name: str = Field(..., description="Ticker if company, otherwise industry/sector name")
    transmission_channel: str = Field(..., description="Economic mechanism")
    transmission_elasticity: float = Field(default=1.0, ge=-2.0, le=2.0)
    raw_magnitude: float = Field(..., ge=-5.0, le=5.0)
    probability: float = Field(..., ge=0.0, le=1.0)
    lag_time_months: int = Field(..., ge=0)
    downstream_ripples: List["RippleConsequence"] = Field(default_factory=list)

class PrimaryConsequence(BaseSchema):
    target_type: str = Field(..., description="Sector|Industry|Company")
    target_name: str
    transmission_channel: str
    raw_magnitude: float = Field(..., ge=-5.0, le=5.0)
    probability: float = Field(..., ge=0.0, le=1.0)
    lag_time_months: int = Field(default=0)
    second_order_effects: List[RippleConsequence] = Field(default_factory=list)

class MacroEventExtraction(BaseSchema):
    event_name: str
    event_category: str
    primary_effects: List[PrimaryConsequence] = Field(default_factory=list)

class VisualArtifact(BaseSchema):
    timestamp_seconds: int
    artifact_type: str = Field(..., description="Financial_Table_Slide|Value_Chain_Diagram|Factory_Floor_Tour|Product_Tear_Down|CapEx_Timeline_Roadmap")
    on_screen_text_ocr: str
    visual_insights: str
    structured_data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    target_ticker: Optional[str] = None
    moat_impact: Optional[str] = None
    visual_description: str = Field(default="")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    frame_snapshot_url: Optional[str] = None

class VideoIntelligenceExtraction(BaseSchema):
    video_summary: str
    spoken_policy_signals: List[Dict[str, Any]] = Field(default_factory=list)
    visual_artifacts: List[VisualArtifact] = Field(default_factory=list)
