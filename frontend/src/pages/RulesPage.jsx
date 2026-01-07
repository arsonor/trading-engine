import { useEffect, useState } from 'react';
import { useRulesStore } from '../store';
import { format } from 'date-fns';
import RuleForm from '../components/RuleForm';

function RulesPage() {
  const { rules, loading, fetchRules, toggleRule, deleteRule, createRule } = useRulesStore();
  const [expandedRule, setExpandedRule] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const handleToggle = async (ruleId, e) => {
    e.stopPropagation();
    await toggleRule(ruleId);
  };

  const handleDelete = async (ruleId, e) => {
    e.stopPropagation();
    if (window.confirm('Are you sure you want to delete this rule?')) {
      await deleteRule(ruleId);
    }
  };

  const handleCreateRule = async (ruleData) => {
    await createRule(ruleData);
    setShowCreateForm(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-gray-900">Trading Rules</h2>
        <div className="flex items-center space-x-4">
          <span className="text-sm text-gray-500">
            {rules.filter((r) => r.is_active).length} of {rules.length} active
          </span>
          {!showCreateForm && (
            <button
              onClick={() => setShowCreateForm(true)}
              className="btn btn-primary"
            >
              + Create Rule
            </button>
          )}
        </div>
      </div>

      {/* Create Rule Form */}
      {showCreateForm && (
        <div className="card">
          <h3 className="text-xl font-semibold text-gray-900 mb-4">Create New Rule</h3>
          <RuleForm
            onSubmit={handleCreateRule}
            onCancel={() => setShowCreateForm(false)}
          />
        </div>
      )}

      {/* Rules List */}
      <div className="space-y-4">
        {loading ? (
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500 mx-auto"></div>
            <p className="mt-2 text-gray-500">Loading rules...</p>
          </div>
        ) : rules.length === 0 && !showCreateForm ? (
          <div className="text-center py-8">
            <p className="text-gray-500">No rules configured</p>
            <p className="text-sm text-gray-400 mt-2">
              Click "Create Rule" to add your first trading rule
            </p>
          </div>
        ) : (
          rules.map((rule) => (
            <div
              key={rule.id}
              className={`card cursor-pointer transition-all ${
                expandedRule === rule.id ? 'ring-2 ring-primary-500' : ''
              }`}
              onClick={() =>
                setExpandedRule(expandedRule === rule.id ? null : rule.id)
              }
            >
              <div className="flex justify-between items-start">
                <div>
                  <div className="flex items-center space-x-3">
                    <span className="text-lg font-semibold text-gray-900">
                      {rule.name}
                    </span>
                    <span className="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-700">
                      {rule.rule_type}
                    </span>
                    <span
                      className={`status-badge ${
                        rule.is_active
                          ? 'status-badge-active'
                          : 'status-badge-inactive'
                      }`}
                    >
                      {rule.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  {rule.description && (
                    <p className="mt-1 text-sm text-gray-500">
                      {rule.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={(e) => handleToggle(rule.id, e)}
                    className={`btn ${
                      rule.is_active ? 'btn-secondary' : 'btn-primary'
                    }`}
                  >
                    {rule.is_active ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={(e) => handleDelete(rule.id, e)}
                    className="btn btn-danger"
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="mt-3 flex items-center space-x-6 text-sm text-gray-500">
                <span>Priority: {rule.priority}</span>
                <span>Alerts: {rule.alerts_triggered}</span>
                <span>
                  Created: {format(new Date(rule.created_at), 'MMM d, yyyy')}
                </span>
                <span>
                  Updated: {format(new Date(rule.updated_at), 'MMM d, yyyy')}
                </span>
              </div>

              {/* Expanded Config */}
              {expandedRule === rule.id && (
                <div className="mt-4 pt-4 border-t border-gray-200">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">
                    Configuration (YAML)
                  </h4>
                  <pre className="bg-gray-50 p-4 rounded-lg text-sm overflow-x-auto">
                    {rule.config_yaml}
                  </pre>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Info Box */}
      <div className="card bg-blue-50 border-blue-200">
        <h3 className="text-sm font-medium text-blue-800">
          About Trading Rules
        </h3>
        <p className="mt-1 text-sm text-blue-700">
          Rules define conditions for generating trading alerts. Each rule
          specifies conditions (price, volume, etc.), filters (min/max price),
          and targets (stop loss, take profit). Rules are evaluated against
          real-time market data.
        </p>
      </div>
    </div>
  );
}

export default RulesPage;
