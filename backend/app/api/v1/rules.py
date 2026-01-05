"""Rules API endpoints."""

from typing import List

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Alert as AlertModel
from app.models import Rule as RuleModel
from app.schemas import Rule, RuleCreate, RuleUpdate

router = APIRouter()


def validate_yaml_config(config_yaml: str) -> None:
    """Validate YAML configuration."""
    try:
        parsed = yaml.safe_load(config_yaml)
        if not isinstance(parsed, dict):
            raise ValueError("Configuration must be a YAML object")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {str(e)}")


@router.get("", response_model=List[Rule])
async def list_rules(
    db: AsyncSession = Depends(get_db),
) -> List[Rule]:
    """List all rules."""
    query = select(RuleModel).order_by(RuleModel.priority.desc(), RuleModel.name)
    result = await db.execute(query)
    rules = result.scalars().all()

    # Get alert counts for each rule
    rule_ids = [r.id for r in rules]
    if rule_ids:
        counts_query = (
            select(AlertModel.rule_id, func.count(AlertModel.id))
            .where(AlertModel.rule_id.in_(rule_ids))
            .group_by(AlertModel.rule_id)
        )
        counts_result = await db.execute(counts_query)
        counts = {row[0]: row[1] for row in counts_result.all()}
    else:
        counts = {}

    return [
        Rule(
            id=rule.id,
            name=rule.name,
            description=rule.description,
            rule_type=rule.rule_type,
            config_yaml=rule.config_yaml,
            is_active=rule.is_active,
            priority=rule.priority,
            alerts_triggered=counts.get(rule.id, 0),
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )
        for rule in rules
    ]


@router.post("", response_model=Rule, status_code=201)
async def create_rule(
    rule_create: RuleCreate,
    db: AsyncSession = Depends(get_db),
) -> Rule:
    """Create a new rule."""
    # Validate YAML
    try:
        validate_yaml_config(rule_create.config_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check for duplicate name
    existing_query = select(RuleModel).where(RuleModel.name == rule_create.name)
    existing = (await db.execute(existing_query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Rule with name '{rule_create.name}' already exists"
        )

    # Create rule
    rule = RuleModel(
        name=rule_create.name,
        description=rule_create.description,
        rule_type=rule_create.rule_type.value,
        config_yaml=rule_create.config_yaml,
        is_active=rule_create.is_active,
        priority=rule_create.priority,
    )

    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return Rule(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type,
        config_yaml=rule.config_yaml,
        is_active=rule.is_active,
        priority=rule.priority,
        alerts_triggered=0,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/{rule_id}", response_model=Rule)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> Rule:
    """Get rule by ID."""
    query = select(RuleModel).where(RuleModel.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule with ID {rule_id} not found")

    # Get alert count
    count_query = select(func.count(AlertModel.id)).where(AlertModel.rule_id == rule_id)
    alerts_triggered = (await db.execute(count_query)).scalar() or 0

    return Rule(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type,
        config_yaml=rule.config_yaml,
        is_active=rule.is_active,
        priority=rule.priority,
        alerts_triggered=alerts_triggered,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.put("/{rule_id}", response_model=Rule)
async def update_rule(
    rule_id: int,
    rule_update: RuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> Rule:
    """Update a rule."""
    query = select(RuleModel).where(RuleModel.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule with ID {rule_id} not found")

    # Validate YAML if provided
    if rule_update.config_yaml is not None:
        try:
            validate_yaml_config(rule_update.config_yaml)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Check for duplicate name if changing
    if rule_update.name is not None and rule_update.name != rule.name:
        existing_query = select(RuleModel).where(RuleModel.name == rule_update.name)
        existing = (await db.execute(existing_query)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409, detail=f"Rule with name '{rule_update.name}' already exists"
            )

    # Update fields
    if rule_update.name is not None:
        rule.name = rule_update.name
    if rule_update.description is not None:
        rule.description = rule_update.description
    if rule_update.config_yaml is not None:
        rule.config_yaml = rule_update.config_yaml
    if rule_update.is_active is not None:
        rule.is_active = rule_update.is_active
    if rule_update.priority is not None:
        rule.priority = rule_update.priority

    await db.commit()
    await db.refresh(rule)

    # Get alert count
    count_query = select(func.count(AlertModel.id)).where(AlertModel.rule_id == rule_id)
    alerts_triggered = (await db.execute(count_query)).scalar() or 0

    return Rule(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type,
        config_yaml=rule.config_yaml,
        is_active=rule.is_active,
        priority=rule.priority,
        alerts_triggered=alerts_triggered,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a rule."""
    query = select(RuleModel).where(RuleModel.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule with ID {rule_id} not found")

    await db.delete(rule)
    await db.commit()


@router.post("/{rule_id}/toggle", response_model=Rule)
async def toggle_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> Rule:
    """Toggle rule active status."""
    query = select(RuleModel).where(RuleModel.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule with ID {rule_id} not found")

    rule.is_active = not rule.is_active
    await db.commit()
    await db.refresh(rule)

    # Get alert count
    count_query = select(func.count(AlertModel.id)).where(AlertModel.rule_id == rule_id)
    alerts_triggered = (await db.execute(count_query)).scalar() or 0

    return Rule(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type,
        config_yaml=rule.config_yaml,
        is_active=rule.is_active,
        priority=rule.priority,
        alerts_triggered=alerts_triggered,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
