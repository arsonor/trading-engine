import { useState } from 'react';

const RULE_TYPES = [
  { value: 'price', label: 'Price' },
  { value: 'volume', label: 'Volume' },
  { value: 'gap', label: 'Gap' },
  { value: 'technical', label: 'Technical' },
];

const CONDITION_FIELDS = [
  { value: 'price', label: 'Price' },
  { value: 'volume', label: 'Volume' },
  { value: 'volume_ratio', label: 'Volume Ratio' },
  { value: 'change_percent', label: 'Change %' },
  { value: 'gap_percent', label: 'Gap %' },
  { value: 'day_high', label: 'Day High' },
  { value: 'day_low', label: 'Day Low' },
  { value: 'vwap', label: 'VWAP' },
];

const OPERATORS = [
  { value: '>', label: '> (greater than)' },
  { value: '>=', label: '>= (greater or equal)' },
  { value: '<', label: '< (less than)' },
  { value: '<=', label: '<= (less or equal)' },
  { value: '==', label: '== (equal)' },
  { value: '!=', label: '!= (not equal)' },
];

function RuleForm({ onSubmit, onCancel }) {
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    rule_type: 'volume',
    priority: 10,
    is_active: true,
    conditions: [{ field: 'price', operator: '>', value: 100 }],
    filters: {
      min_price: '',
      max_price: '',
      min_volume: '',
    },
    targets: {
      stop_loss_percent: -3.0,
      target_percent: '',
      target_rr_ratio: 2.0,
    },
    confidence: {
      base_score: 0.75,
    },
  });

  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
  };

  const handleNestedChange = (section, field, value) => {
    setFormData((prev) => ({
      ...prev,
      [section]: {
        ...prev[section],
        [field]: value,
      },
    }));
  };

  const handleConditionChange = (index, field, value) => {
    setFormData((prev) => ({
      ...prev,
      conditions: prev.conditions.map((cond, i) =>
        i === index ? { ...cond, [field]: value } : cond
      ),
    }));
  };

  const addCondition = () => {
    setFormData((prev) => ({
      ...prev,
      conditions: [
        ...prev.conditions,
        { field: 'price', operator: '>', value: 0 },
      ],
    }));
  };

  const removeCondition = (index) => {
    if (formData.conditions.length > 1) {
      setFormData((prev) => ({
        ...prev,
        conditions: prev.conditions.filter((_, i) => i !== index),
      }));
    }
  };

  const buildConfigYaml = () => {
    const config = {
      conditions: formData.conditions.map((c) => ({
        field: c.field,
        operator: c.operator,
        value: parseFloat(c.value),
      })),
    };

    // Add filters (only non-empty values)
    const filters = {};
    if (formData.filters.min_price) filters.min_price = parseFloat(formData.filters.min_price);
    if (formData.filters.max_price) filters.max_price = parseFloat(formData.filters.max_price);
    if (formData.filters.min_volume) filters.min_volume = parseFloat(formData.filters.min_volume);
    if (Object.keys(filters).length > 0) config.filters = filters;

    // Add targets
    const targets = {};
    if (formData.targets.stop_loss_percent) targets.stop_loss_percent = parseFloat(formData.targets.stop_loss_percent);
    if (formData.targets.target_percent) targets.target_percent = parseFloat(formData.targets.target_percent);
    if (formData.targets.target_rr_ratio) targets.target_rr_ratio = parseFloat(formData.targets.target_rr_ratio);
    if (Object.keys(targets).length > 0) config.targets = targets;

    // Add confidence
    if (formData.confidence.base_score) {
      config.confidence = { base_score: parseFloat(formData.confidence.base_score) };
    }

    // Convert to YAML-like JSON string (simple inline format)
    return JSON.stringify(config);
  };

  const validate = () => {
    const newErrors = {};
    if (!formData.name.trim()) newErrors.name = 'Name is required';
    if (formData.conditions.length === 0) newErrors.conditions = 'At least one condition is required';
    formData.conditions.forEach((cond, i) => {
      if (!cond.value && cond.value !== 0) {
        newErrors[`condition_${i}`] = 'Value is required';
      }
    });
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validate()) return;

    setSubmitting(true);
    try {
      const ruleData = {
        name: formData.name,
        description: formData.description || null,
        rule_type: formData.rule_type,
        config_yaml: buildConfigYaml(),
        is_active: formData.is_active,
        priority: parseInt(formData.priority) || 0,
      };
      await onSubmit(ruleData);
    } catch (error) {
      setErrors({ submit: error.message || 'Failed to create rule' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Basic Info */}
      <div className="space-y-4">
        <h3 className="text-lg font-medium text-gray-900">Basic Information</h3>

        <div>
          <label className="block text-sm font-medium text-gray-700">
            Rule Name *
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleChange}
            className={`mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm ${errors.name ? 'border-red-500' : ''}`}
            placeholder="e.g., Volume Spike Alert"
          />
          {errors.name && <p className="mt-1 text-sm text-red-500">{errors.name}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">
            Description
          </label>
          <textarea
            name="description"
            value={formData.description}
            onChange={handleChange}
            rows={2}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            placeholder="Describe what this rule detects..."
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Rule Type
            </label>
            <select
              name="rule_type"
              value={formData.rule_type}
              onChange={handleChange}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            >
              {RULE_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">
              Priority
            </label>
            <input
              type="number"
              name="priority"
              value={formData.priority}
              onChange={handleChange}
              min="0"
              max="100"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>
        </div>

        <div className="flex items-center">
          <input
            type="checkbox"
            name="is_active"
            checked={formData.is_active}
            onChange={handleChange}
            className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
          <label className="ml-2 text-sm text-gray-700">
            Active (rule will evaluate immediately)
          </label>
        </div>
      </div>

      {/* Conditions */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-medium text-gray-900">Conditions *</h3>
          <button
            type="button"
            onClick={addCondition}
            className="btn btn-secondary text-sm"
          >
            + Add Condition
          </button>
        </div>

        {formData.conditions.map((condition, index) => (
          <div key={index} className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
            <select
              value={condition.field}
              onChange={(e) => handleConditionChange(index, 'field', e.target.value)}
              className="block rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            >
              {CONDITION_FIELDS.map((field) => (
                <option key={field.value} value={field.value}>
                  {field.label}
                </option>
              ))}
            </select>

            <select
              value={condition.operator}
              onChange={(e) => handleConditionChange(index, 'operator', e.target.value)}
              className="block rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            >
              {OPERATORS.map((op) => (
                <option key={op.value} value={op.value}>
                  {op.label}
                </option>
              ))}
            </select>

            <input
              type="number"
              step="any"
              value={condition.value}
              onChange={(e) => handleConditionChange(index, 'value', e.target.value)}
              className="block w-24 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="Value"
            />

            {formData.conditions.length > 1 && (
              <button
                type="button"
                onClick={() => removeCondition(index)}
                className="text-red-500 hover:text-red-700"
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {errors.conditions && <p className="text-sm text-red-500">{errors.conditions}</p>}
      </div>

      {/* Filters */}
      <div className="space-y-4">
        <h3 className="text-lg font-medium text-gray-900">Filters (Optional)</h3>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Min Price ($)
            </label>
            <input
              type="number"
              step="0.01"
              value={formData.filters.min_price}
              onChange={(e) => handleNestedChange('filters', 'min_price', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., 10"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Max Price ($)
            </label>
            <input
              type="number"
              step="0.01"
              value={formData.filters.max_price}
              onChange={(e) => handleNestedChange('filters', 'max_price', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., 500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Min Volume
            </label>
            <input
              type="number"
              value={formData.filters.min_volume}
              onChange={(e) => handleNestedChange('filters', 'min_volume', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., 100000"
            />
          </div>
        </div>
      </div>

      {/* Targets */}
      <div className="space-y-4">
        <h3 className="text-lg font-medium text-gray-900">Targets</h3>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Stop Loss (%)
            </label>
            <input
              type="number"
              step="0.1"
              value={formData.targets.stop_loss_percent}
              onChange={(e) => handleNestedChange('targets', 'stop_loss_percent', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., -3"
            />
            <p className="mt-1 text-xs text-gray-500">Negative value (e.g., -3 for 3% below)</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Target (%)
            </label>
            <input
              type="number"
              step="0.1"
              value={formData.targets.target_percent}
              onChange={(e) => handleNestedChange('targets', 'target_percent', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., 6"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Risk/Reward Ratio
            </label>
            <input
              type="number"
              step="0.1"
              value={formData.targets.target_rr_ratio}
              onChange={(e) => handleNestedChange('targets', 'target_rr_ratio', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="e.g., 2"
            />
            <p className="mt-1 text-xs text-gray-500">Used if Target % is empty</p>
          </div>
        </div>
      </div>

      {/* Confidence */}
      <div className="space-y-4">
        <h3 className="text-lg font-medium text-gray-900">Confidence</h3>
        <div className="w-1/3">
          <label className="block text-sm font-medium text-gray-700">
            Base Score (0-1)
          </label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={formData.confidence.base_score}
            onChange={(e) => handleNestedChange('confidence', 'base_score', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
          />
        </div>
      </div>

      {/* Error & Buttons */}
      {errors.submit && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-600">{errors.submit}</p>
        </div>
      )}

      <div className="flex justify-end space-x-3 pt-4 border-t">
        <button
          type="button"
          onClick={onCancel}
          className="btn btn-secondary"
          disabled={submitting}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting}
        >
          {submitting ? 'Creating...' : 'Create Rule'}
        </button>
      </div>
    </form>
  );
}

export default RuleForm;
