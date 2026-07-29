"""Phase 3.5: drop v1 alert columns, rename symbol to ticker, drop rules

Revision ID: c653a931ecaf
Revises: 0ca0181ab014
Create Date: 2026-07-29 12:42:24.288163

"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c653a931ecaf'
down_revision: Union[str, Sequence[str], None] = '0ca0181ab014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# v1 columns removed from `alerts`. Every one was populated only by the rule engine,
# which no longer exists.
V1_ALERT_COLUMNS = (
    "setup_type",
    "entry_price",
    "stop_loss",
    "target_price",
    "market_data_json",
)


def upgrade() -> None:
    """Upgrade schema — remove the v1 vestiges from `alerts` and drop `rules`.

    ## Decision: v1-origin alert rows are DELETED

    A v1-origin row is one with `session_date IS NULL` — only the v2 scanner sets that
    column, so it is an exact marker of provenance.

    Everything that gave such a row meaning is dropped by this same migration:
    `setup_type`, `entry_price`, `stop_loss`, `target_price`, `market_data_json` and the
    link to its `rule`. What would survive is a ticker, a timestamp and a confidence
    score with no setup, no price and no session.

    Those husks would also be permanently invisible. Both read paths filter on
    `session_date` — `/api/v1/scanner/alerts` selects `max(session_date)` and matches on
    it, and `ScannerAlertService.session_alerts` requires `session_date IS NOT NULL` — so
    a NULL-session row can never appear in the dashboard, the API or a broadcast. Keeping
    them would preserve rows that no code reads and whose content is gone, and would
    mislead anyone who later queried the table directly.

    The count is logged before the delete so the deploy record shows what was removed.
    Rejected alternative — keeping them with null v2 fields — is more conservative but
    preserves the husk, not the data.

    ## Decision: the `rules` table is DROPPED

    `docs/CLAUDE.md` section 5 originally said `rules` would hold tunable scanner
    thresholds. Phase 3 built `scanner_settings` for precisely that: typed columns,
    validated on write, with an env-default fallback. `rules` stores free-text
    `config_yaml` for the retired per-tick engine and was left orphaned — after Phase 3.5
    no code reads or writes it. Section 5 has been updated to match.
    """
    bind = op.get_bind()

    v1_rows = bind.execute(
        sa.text("SELECT count(*) FROM alerts WHERE session_date IS NULL")
    ).scalar_one()
    if v1_rows:
        logger.info(
            "Deleting %s v1-origin alert row(s) (session_date IS NULL). Their defining "
            "columns are dropped by this migration and they are unreachable by every "
            "read path; see the upgrade docstring.",
            v1_rows,
        )
        bind.execute(sa.text("DELETE FROM alerts WHERE session_date IS NULL"))

    # --- alerts: drop the v1 columns and the link to `rules` ---------------------
    op.drop_constraint('alerts_rule_id_fkey', 'alerts', type_='foreignkey')
    op.drop_column('alerts', 'rule_id')
    for column in V1_ALERT_COLUMNS:
        op.drop_column('alerts', column)

    # --- alerts: symbol -> ticker, with its index and unique constraint ----------
    # RENAME (not add/copy/drop) so the data moves with the column and the operation
    # stays a catalog change rather than a table rewrite.
    op.drop_constraint('uq_alerts_symbol_session', 'alerts', type_='unique')
    op.alter_column('alerts', 'symbol', new_column_name='ticker')
    op.execute('ALTER INDEX ix_alerts_symbol RENAME TO ix_alerts_ticker')
    op.create_unique_constraint(
        'uq_alerts_ticker_session', 'alerts', ['ticker', 'session_date']
    )

    # --- drop the orphaned rules table -------------------------------------------
    op.drop_index(op.f('ix_rules_name'), table_name='rules')
    op.drop_index(op.f('ix_rules_id'), table_name='rules')
    op.drop_table('rules')


def downgrade() -> None:
    """Downgrade schema — restore the v1 shape.

    ## What is restored

    The `rules` table, the `alerts.rule_id` FK, the five v1 columns, and the `symbol`
    column name with its index and unique constraint. The schema after a downgrade is
    exactly what revision 0ca0181ab014 produced.

    ## What is NOT restored, and cannot be

    * **The v1 columns come back NULLABLE.** They were nullable at 0ca0181ab014 —
      relaxed there precisely because scanner alerts have no honest values for them — so
      this restores the real previous state rather than the original v1 one.
    * **Dropped column data is gone.** Downgrading yields empty `setup_type`,
      `entry_price`, `stop_loss`, `target_price` and `market_data_json` columns. The
      values went with the columns.
    * **Deleted v1-origin alert rows are not resurrected.** The upgrade removed them; a
      downgrade cannot know what they contained.
    * **`rules` comes back empty.** Its rows were dropped with the table.

    Take a backup before downgrading a database you care about. Documented in README.md
    under "Rolling back".
    """
    # --- recreate `rules` (empty) before anything references it ------------------
    op.create_table(
        'rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('rule_type', sa.String(length=50), nullable=False),
        sa.Column('config_yaml', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rules_id'), 'rules', ['id'], unique=False)
    op.create_index(op.f('ix_rules_name'), 'rules', ['name'], unique=True)

    # --- alerts: ticker -> symbol ------------------------------------------------
    op.drop_constraint('uq_alerts_ticker_session', 'alerts', type_='unique')
    op.alter_column('alerts', 'ticker', new_column_name='symbol')
    op.execute('ALTER INDEX ix_alerts_ticker RENAME TO ix_alerts_symbol')
    op.create_unique_constraint(
        'uq_alerts_symbol_session', 'alerts', ['symbol', 'session_date']
    )

    # --- alerts: restore the v1 columns, NULLABLE (see the docstring) ------------
    op.add_column('alerts', sa.Column('setup_type', sa.String(length=50), nullable=True))
    op.add_column('alerts', sa.Column('entry_price', sa.Float(), nullable=True))
    op.add_column('alerts', sa.Column('stop_loss', sa.Float(), nullable=True))
    op.add_column('alerts', sa.Column('target_price', sa.Float(), nullable=True))
    op.add_column('alerts', sa.Column('market_data_json', sa.JSON(), nullable=True))
    op.add_column('alerts', sa.Column('rule_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'alerts_rule_id_fkey', 'alerts', 'rules', ['rule_id'], ['id'], ondelete='SET NULL'
    )
