import {
  ArrowLeftOutlined,
  BellOutlined,
  FileDoneOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Empty,
  Spin,
  Tag,
  message,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { ApiError, getPolicyBenefits, listPolicies } from './api';
import { ClaimFormModal, ClaimsDrawer } from './ClaimsUI';
import type { AdditionalPolicy, AuthSession, PolicyBenefits } from './types';

interface PolicyCenterPageProps {
  session: AuthSession;
  onBack: () => void;
  onLogout: () => void;
  onAccount: () => void;
}

const POLICY_STATUS_LABELS: Record<string, string> = {
  pending: '待生效',
  active: '生效中',
  expired: '已到期',
  terminated: '已终止',
};

const PAYMENT_FREQUENCY_LABELS: Record<string, string> = {
  single: '单次交清',
  annual: '年交',
  monthly: '月交',
  quarterly: '季交',
};

function statusLabel(value: string | null | undefined): string {
  return (value && POLICY_STATUS_LABELS[value]) || value || '—';
}

function paymentLabel(value: string | null | undefined): string {
  return (value && PAYMENT_FREQUENCY_LABELS[value]) || value || '—';
}

function productName(policy: AdditionalPolicy): string {
  const name = policy.product?.name;
  if (typeof name === 'string' && name) return name;
  return '保险保单';
}

function formatMoney(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN') : String(value);
}

function formatDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : '—';
}

export function PolicyCenterPage({ session, onBack, onLogout, onAccount }: PolicyCenterPageProps) {
  const [policies, setPolicies] = useState<AdditionalPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [benefitsPolicy, setBenefitsPolicy] = useState<AdditionalPolicy | null>(null);
  const [benefits, setBenefits] = useState<PolicyBenefits | null>(null);
  const [benefitsLoading, setBenefitsLoading] = useState(false);
  const [claimPolicy, setClaimPolicy] = useState<AdditionalPolicy | null>(null);
  const [claimsOpen, setClaimsOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const token = session.token;

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPolicies(await listPolicies(token));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '保单加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadPolicies();
  }, [loadPolicies, refreshKey]);

  async function openBenefits(policy: AdditionalPolicy) {
    if (!policy.id) return;
    setBenefitsPolicy(policy);
    setBenefits(null);
    setBenefitsLoading(true);
    try {
      setBenefits(await getPolicyBenefits(token, policy.id));
    } catch (reason) {
      message.error(reason instanceof ApiError ? reason.message : '权益解析失败，请稍后重试');
      setBenefitsPolicy(null);
    } finally {
      setBenefitsLoading(false);
    }
  }

  const activePolicies = policies.filter((policy) => policy.status === 'active');
  const expiringPolicies = activePolicies.filter((policy) => policy.expire_soon);
  const expiredPolicies = policies.filter((policy) => policy.status === 'expired');

  return (
    <div className="page-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); onBack(); }} aria-label="安心保首页">
            <span className="brand__mark"><SafetyCertificateOutlined /></span>
            <span><strong>安心保</strong><small>保险优选平台</small></span>
          </a>
          <nav className="site-nav" aria-label="主导航">
            <a href="/" onClick={(event) => { event.preventDefault(); onBack(); }}>保险产品</a>
            <a className="is-active" href="/policies" onClick={(event) => event.preventDefault()}>保单中心</a>
            <a href="/account" onClick={(event) => { event.preventDefault(); onAccount(); }}>个人中心</a>
          </nav>
          <div className="site-actions">
            <a className="user-name" href="/account" onClick={(event) => { event.preventDefault(); onAccount(); }} title="进入用户中心">
              {session.user.displayName || session.user.username}
            </a>
            <Button type="text" onClick={onLogout}>退出</Button>
          </div>
        </div>
      </header>

      <main className="policy-center">
        <section className="policy-hero">
          <h1>保单中心</h1>
          <p>集中管理名下保单，权益条款一键解析，到期自动提醒</p>
        </section>

        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {loading ? <div className="policy-center__loading"><Spin /></div> : null}

        {!loading && !error && policies.length === 0 ? (
          <div className="policy-center__empty">
            <Empty description="名下暂无保单，可在智能顾问投保后查看">
              <Button type="primary" onClick={onBack}>去挑选保障</Button>
            </Empty>
          </div>
        ) : null}

        {!loading && policies.length > 0 ? (
          <>
            {expiringPolicies.length > 0 ? (
              <Alert
                className="policy-alert"
                type="warning"
                showIcon
                icon={<BellOutlined />}
                message={`${expiringPolicies.length} 份保单即将到期`}
                description={expiringPolicies.map((policy) => (
                  <div key={policy.id} className="policy-alert__row">
                    <span>{productName(policy)}</span>
                    <strong>
                      {typeof policy.days_to_expire === 'number'
                        ? `剩余 ${policy.days_to_expire} 天（${formatDate(policy.expires_at)} 到期）`
                        : formatDate(policy.expires_at)}
                    </strong>
                  </div>
                ))}
              />
            ) : null}
            {expiredPolicies.length > 0 ? (
              <Alert
                className="policy-alert"
                type="info"
                showIcon
                message={`${expiredPolicies.length} 份保单已到期`}
                description={expiredPolicies.map((policy) => (
                  <div key={policy.id} className="policy-alert__row">
                    <span>{productName(policy)}</span>
                    <strong>{formatDate(policy.expires_at)} 到期</strong>
                  </div>
                ))}
              />
            ) : null}
            {expiringPolicies.length === 0 && expiredPolicies.length === 0 ? (
              <Alert
                className="policy-alert"
                type="success"
                showIcon
                icon={<FileDoneOutlined />}
                message="保障运行正常"
                description="名下保单均在有效期内且 30 天内无到期保单。"
              />
            ) : null}

            <div className="policy-grid">
              {policies.map((policy) => (
                <article className="policy-card" key={policy.id}>
                  <div className="policy-card__top">
                    <strong>{productName(policy)}</strong>
                    <span className={`policy-status policy-status--${policy.status ?? ''}`}>
                      {statusLabel(policy.status)}
                    </span>
                  </div>
                  <dl className="policy-card__meta">
                    <div><dt>保单号</dt><dd>{policy.policy_number ?? '—'}</dd></div>
                    <div><dt>保险公司</dt><dd>{policy.product?.insurer ?? '—'}</dd></div>
                    <div><dt>被保险人</dt><dd>{policy.insured_name ?? '—'}</dd></div>
                    <div><dt>保额</dt><dd>¥{formatMoney(policy.coverage_amount)}</dd></div>
                    <div><dt>保费</dt><dd>¥{formatMoney(policy.premium_amount)}（{paymentLabel(policy.payment_frequency)}）</dd></div>
                    <div>
                      <dt>保障期间</dt>
                      <dd>
                        {formatDate(policy.effective_at)} 至 {formatDate(policy.expires_at)}
                        {typeof policy.days_to_expire === 'number' && policy.status === 'active' ? (
                          policy.days_to_expire <= 30 ? (
                            <Tag color={policy.days_to_expire < 0 ? 'default' : 'orange'} style={{ marginLeft: 8 }}>
                              {policy.days_to_expire < 0 ? '已到期' : `剩余 ${policy.days_to_expire} 天`}
                            </Tag>
                          ) : null
                        ) : null}
                      </dd>
                    </div>
                  </dl>
                  <div className="policy-card__actions">
                    <Button type="primary" size="small" onClick={() => openBenefits(policy)}>
                      保障权益解析
                    </Button>
                    {policy.status === 'active' ? (
                      <Button size="small" onClick={() => setClaimPolicy(policy)}>申请理赔</Button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>

            <div className="policy-center__claims">
              <Button icon={<FileDoneOutlined />} onClick={() => setClaimsOpen(true)}>
                查看理赔记录
              </Button>
            </div>
          </>
        ) : null}
      </main>

      <Drawer
        title={benefitsPolicy ? `保障权益 · ${productName(benefitsPolicy)}` : '保障权益'}
        width={560}
        open={Boolean(benefitsPolicy)}
        onClose={() => setBenefitsPolicy(null)}
      >
        {benefitsLoading ? <Spin /> : null}
        {benefits && !benefitsLoading ? (
          benefits.benefits.length === 0 ? (
            <Empty description="暂未匹配到该产品的条款知识库" />
          ) : (
            <>
              {benefits.document_name ? (
                <p className="benefit-source">
                  条款来源：{benefits.document_name}
                </p>
              ) : null}
              <Collapse
                className="benefit-collapse"
                items={benefits.benefits.map((benefit, index) => ({
                  key: `${benefit.section}-${index}`,
                  label: (
                    <span className="benefit-collapse__label">
                      {benefit.section}
                      <Tag style={{ marginLeft: 8 }}>第 {benefit.page_no + 1} 页</Tag>
                    </span>
                  ),
                  children: (
                    <div className="benefit-content">
                      {benefit.content}
                    </div>
                  ),
                }))}
                defaultActiveKey={benefits.benefits.length ? [`${benefits.benefits[0].section}-0`] : []}
              />
            </>
          )
        ) : null}
      </Drawer>

      <ClaimFormModal
        session={session}
        policy={claimPolicy}
        onClose={() => setClaimPolicy(null)}
        onCreated={() => {
          setClaimPolicy(null);
          setRefreshKey((key) => key + 1);
        }}
      />
      <ClaimsDrawer
        session={session}
        open={claimsOpen}
        onClose={() => setClaimsOpen(false)}
        refreshKey={refreshKey}
      />
    </div>
  );
}
