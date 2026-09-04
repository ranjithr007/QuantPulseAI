from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from app.database.sqlserver import Base


class StrategyLearningEvaluation(Base):
    __tablename__ = "strategy_learning_evaluations"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    strategy_version = Column(String(100), nullable=False, index=True)
    milestone = Column(Integer, nullable=False)
    window_size = Column(Integer, nullable=False, default=30)
    closed_trade_count = Column(Integer, nullable=False)
    status = Column(String(40), nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    diagnostics_json = Column(Text, nullable=False)
    recommended_changes_json = Column(Text, nullable=False)
    candidate_version = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "strategy_version",
            "milestone",
            name="uq_strategy_learning_evaluation_milestone",
        ),
    )


class StrategyVersionConfig(Base):
    __tablename__ = "strategy_version_configs"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    version = Column(String(100), nullable=False)
    base_version = Column(String(100), nullable=False)
    decision_version = Column(String(120), nullable=False)
    status = Column(String(40), nullable=False, index=True)
    parameters_json = Column(Text, nullable=False)
    source_evaluation_id = Column(Integer, nullable=True, index=True)
    paper_execution_enabled = Column(Boolean, nullable=False, default=True)
    official_paper_enabled = Column(Boolean, nullable=False, default=False)
    live_execution_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "version",
            name="uq_strategy_version_config_identity",
        ),
    )


Index(
    "ix_strategy_learning_latest",
    StrategyLearningEvaluation.strategy_id,
    StrategyLearningEvaluation.strategy_version,
    StrategyLearningEvaluation.created_at,
    StrategyLearningEvaluation.id,
)
