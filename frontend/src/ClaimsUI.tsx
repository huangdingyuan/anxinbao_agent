import { FileProtectOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Spin,
  message,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { advanceClaimStatus, ApiError, createClaim, listClaims } from './api';
import type { AdditionalPolicy, AuthSession, ClaimRecord } from './types';

const CLAIM_TYPE_OPTIONS = [
  { value: 'medical', label: '医疗费用' },
  { value: 'accident', label: '意外伤害' },
  { value: 'critical_illness', label: '重大疾病' },
  { value: 'life', label: '身故/全残' },
];

const CLAIM_STATUS_LABELS: Record<string, string> = {
  submitted: '已提交',
  reviewing: '审核中',
  approved: '已通过',
  rejected: '已拒绝',
  paid: '已赔付',
};

// 与后端 STATUS_TRANSITIONS 对齐的演示流转图
const CLAIM_STATUS_FLOW: Record<string, string[]> = {
  submitted: ['reviewing'],
  reviewing: ['approved', 'rejected'],
  approved: ['paid'],
  rejected: [],
  paid: [],
};

function claimStatusLabel(value: string): string {
  return CLAIM_STATUS_LABELS[value] ?? value;
}

function claimTypeLabel(value: string): string {
  return CLAIM_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

function formatMoney(value: string | null): string {
  if (value === null || value === undefined) return '—';
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN') : value;
}

function formatTime(value: string): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—';
}

function policyProductName(policy: AdditionalPolicy): string {
  const name = policy.product?.name;
  if (typeof name === 'string' && name) return name;
  return '保单理赔';
}

export function ClaimFormModal({
  session,
  policy,
  onClose,
  onCreated,
}: {
  session: AuthSession;
  policy: AdditionalPolicy | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const token = session.token;

  useEffect(() => {
    if (policy) form.resetFields();
  }, [form, policy]);

  async function handleFinish(values: { claim_type: string; amount?: number; description?: string }) {
    if (!policy?.id) return;
    setSubmitting(true);
    try {
      const claim = await createClaim(token, {
        policy_id: policy.id,
        claim_type: values.claim_type,
        amount: values.amount != null ? String(values.amount) : undefined,
        description: values.description?.trim() || undefined,
      });
      message.success(`理赔申请已提交：${claim.claim_number ?? ''}`);
      onCreated();
    } catch (reason) {
      message.error(reason instanceof ApiError ? reason.message : '理赔申请提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={policy ? `申请理赔 · ${policyProductName(policy)}` : '申请理赔'}
      open={Boolean(policy)}
      onCancel={submitting ? undefined : onClose}
      onOk={() => form.submit()}
      okText="提交理赔申请"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        initialValues={{ claim_type: 'medical' }}
      >
        <Form.Item
          name="claim_type"
          label="理赔类型"
          rules={[{ required: true, message: '请选择理赔类型' }]}
        >
          <Select options={CLAIM_TYPE_OPTIONS} placeholder="请选择理赔类型" />
        </Form.Item>
        <Form.Item
          name="amount"
          label="申请金额"
          rules={[{ required: true, message: '请填写申请金额' }]}
        >
          <InputNumber
            min={0.01}
            precision={2}
            addonBefore="¥"
            style={{ width: '100%' }}
            placeholder="请输入申请理赔金额"
          />
        </Form.Item>
        <Form.Item name="description" label="出险说明">
          <Input.TextArea
            rows={4}
            maxLength={500}
            showCount
            placeholder="简单描述出险经过、就诊医院、费用构成等信息（选填）"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function ClaimsDrawer({
  session,
  open,
  onClose,
  refreshKey,
}: {
  session: AuthSession;
  open: boolean;
  onClose: () => void;
  refreshKey: number;
}) {
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancingId, setAdvancingId] = useState<string | null>(null);
  const token = session.token;

  const loadClaims = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setClaims(await listClaims(token));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '理赔记录加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (open) loadClaims();
  }, [open, refreshKey, loadClaims]);

  async function advance(claim: ClaimRecord, status: string) {
    setAdvancingId(claim.id);
    try {
      const updated = await advanceClaimStatus(token, claim.id, status);
      setClaims((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      message.success(`理赔 ${updated.claim_number ?? ''} 已更新为「${claimStatusLabel(updated.status)}」`);
    } catch (reason) {
      message.error(reason instanceof ApiError ? reason.message : '状态更新失败，请稍后重试');
    } finally {
      setAdvancingId(null);
    }
  }

  return (
    <Drawer
      title="我的理赔记录"
      width={460}
      open={open}
      onClose={onClose}
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={loadClaims}>
          刷新
        </Button>
      }
    >
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {loading ? <Spin /> : null}
      {!loading && !error && claims.length === 0 ? (
        <div className="claims-empty">
          <FileProtectOutlined />
          <p>暂无理赔记录，在保单卡片上点击「申请理赔」即可发起</p>
        </div>
      ) : null}
      <div className="claim-list">
        {claims.map((claim) => (
          <ClaimCard
            key={claim.id}
            claim={claim}
            advancing={advancingId === claim.id}
            onAdvance={advance}
          />
        ))}
      </div>
    </Drawer>
  );
}

function ClaimCard({
  claim,
  advancing,
  onAdvance,
}: {
  claim: ClaimRecord;
  advancing: boolean;
  onAdvance: (claim: ClaimRecord, status: string) => void;
}) {
  const nextStatuses = CLAIM_STATUS_FLOW[claim.status] ?? [];
  return (
    <article className="claim-card">
      <div className="claim-card__top">
        <strong>{claim.claim_number ?? '理赔申请'}</strong>
        <span className={`claim-status claim-status--${claim.status}`}>
          {claimStatusLabel(claim.status)}
        </span>
      </div>
      <dl>
        <div>
          <dt>产品</dt>
          <dd>{claim.policy.product_name ?? '—'}</dd>
        </div>
        <div>
          <dt>保单号</dt>
          <dd>{claim.policy.policy_number}</dd>
        </div>
        <div>
          <dt>理赔类型</dt>
          <dd>{claimTypeLabel(claim.claim_type)}</dd>
        </div>
        <div>
          <dt>申请金额</dt>
          <dd>¥{formatMoney(claim.amount)}</dd>
        </div>
        <div>
          <dt>提交时间</dt>
          <dd>{formatTime(claim.submitted_at)}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{formatTime(claim.updated_at)}</dd>
        </div>
      </dl>
      {claim.description ? <p className="claim-card__desc">{claim.description}</p> : null}
      {nextStatuses.length > 0 ? (
        <div className="claim-card__actions">
          {nextStatuses.map((status) => (
            <Button
              key={status}
              size="small"
              disabled={advancing}
              onClick={() => onAdvance(claim, status)}
            >
              模拟推进 → {claimStatusLabel(status)}
            </Button>
          ))}
        </div>
      ) : null}
    </article>
  );
}
