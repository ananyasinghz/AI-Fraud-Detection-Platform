"""Enumerations shared by contract-v1 models."""

from enum import StrEnum


class IntentType(StrEnum):
    BROAD_EXPLORATION = "broad_exploration"
    SIMPLE_LOOKUP = "simple_lookup"
    THRESHOLD_AGGREGATION = "threshold_aggregation"
    FEATURE_COMPARISON = "feature_comparison"
    PATTERN_SEARCH = "pattern_search"
    ENTITY_INVESTIGATION = "entity_investigation"
    TRANSACTION_SCORING = "transaction_scoring"
    EXPLANATION_REQUEST = "explanation_request"


class TargetScope(StrEnum):
    DATASET = "dataset"
    COHORT = "cohort"
    CUSTOMER = "customer"
    ACCOUNT = "account"
    TRANSACTION = "transaction"


class RouteType(StrEnum):
    SIMPLE_LOOKUP = "simple_lookup"
    FEATURE_ONLY = "feature_only"
    FULL_INVESTIGATION = "full_investigation"


class PatternType(StrEnum):
    STRUCTURING = "structuring"
    SMURFING = "smurfing"
    VELOCITY = "velocity"
    RAPID_CASH_OUT = "rapid_cash_out"
    ROUND_NUMBER = "round_number"
    PROFILE_DEVIATION = "profile_deviation"
    HIGH_RISK_COUNTRY = "high_risk_country"
    GENERAL = "general"


class ToolName(StrEnum):
    SQL_LOOKUP = "sql_lookup"
    EDA = "eda"
    FEATURE_ENGINEERING = "feature_engineering"
    ANOMALY_DETECTION = "anomaly_detection"
    GRAPH_ANALYSIS = "graph_analysis"
    RETRIEVAL = "retrieval"
    RISK_CLASSIFICATION = "risk_classification"
    VERIFICATION = "verification"
    ESCALATION = "escalation"
    EXPLANATION = "explanation"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


class EntityType(StrEnum):
    CUSTOMER = "customer"
    ACCOUNT = "account"
    TRANSACTION = "transaction"


class TransactionDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class FeatureGrouping(StrEnum):
    HOUR = "hour"
    DAY = "day"
    ACCOUNT = "account"
    COUNTERPARTY = "counterparty"
    DEVICE = "device"
    COUNTRY = "country"
    TRANSACTION_TYPE = "transaction_type"


class ValueType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    FLOAT = "float"
    BOOLEAN = "boolean"
    STRING = "string"


class RuleSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EscalationAction(StrEnum):
    MONITOR = "monitor"
    REVIEW = "review"
    REPORT = "report"


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    HISTOGRAM = "histogram"
    SCATTER = "scatter"
    TABLE = "table"
