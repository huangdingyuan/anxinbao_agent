import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  HeartOutlined,
  IdcardOutlined,
  PayCircleOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { Alert, Button, Descriptions, Spin, Steps } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { ApiError, getInsurancePlan, listProducts, markPlanItemInsured } from './api';
import { formatCategoryLabel } from './categoryLabels';
import type { AuthSession, Product } from './types';

interface ApplicationPageProps {
  session: AuthSession;
  onBack: () => void;
  onSessionExpired: () => void;
}

interface PlanItem {
  id: string;
  plan_id?: string;
  product_id: number;
  name?: string;
  category?: string;
  insurer?: string;
  image_url?: string | null;
  description?: string;
  min_premium?: number | null;
  highlights?: string[];
  annual_premium_budget?: number | null;
  recommendation_reason?: string;
  status?: string;
}

interface InsurancePlan {
  id: string;
  name?: string;
  summary?: string;
  annual_premium_budget?: number | null;
  status?: string;
  items?: PlanItem[];
}

const APPLICATION_STEPS = [
  { title: '保费试算', icon: <PayCircleOutlined /> },
  { title: '客户告知', icon: <FileTextOutlined /> },
  { title: '健康告知', icon: <HeartOutlined /> },
  { title: '保单信息', icon: <IdcardOutlined /> },
  { title: '确认支付', icon: <CheckCircleOutlined /> },
];

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `¥${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function ApplicationPage({ session, onBack, onSessionExpired }: ApplicationPageProps) {
  const params = new URLSearchParams(window.location.search);
  const productId = params.get('product_id');
  const planId = params.get('plan_id');
  const itemId = params.get('item_id');
  const [currentStep, setCurrentStep] = useState(0);
  const [paying, setPaying] = useState(false);
  const [paid, setPaid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [product, setProduct] = useState<Product | null>(null);
  const [plan, setPlan] = useState<InsurancePlan | null>(null);

  useEffect(() => {
    let ignore = false;
    async function load() {
      setLoading(true);
      try {
        if (productId) {
          const products = await listProducts('all');
          if (!ignore) setProduct(products.find((p) => String(p.id) === productId) ?? null);
        }
        if (planId) {
          const data = (await getInsurancePlan(session.token, planId)) as InsurancePlan;
          if (!ignore) setPlan(data);
        }
      } catch {
        // 数据加载失败时保留空值，不阻断流程推进
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    void load();
    return () => {
      ignore = true;
    };
  }, [productId, planId, session.token]);

  const item = useMemo(
    () => plan?.items?.find((i) => String(i.id) === itemId) ?? null,
    [plan, itemId],
  );

  const productName = product?.name ?? item?.name ?? (productId ? `产品 ID：${productId}` : '未选择产品');
  const annualPremium = item?.annual_premium_budget ?? plan?.annual_premium_budget ?? null;
  const insuredName = session.user.displayName || session.user.username;

  async function pay() {
    if (!planId || !itemId || paying || paid) return;
    setPaying(true);
    setError(null);
    try {
      await markPlanItemInsured(session.token, planId, itemId);
      setPaid(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        onSessionExpired();
        return;
      }
      setError(reason instanceof Error ? reason.message : '支付失败，请稍后重试');
    } finally {
      setPaying(false);
    }
  }

  const isLastStep = currentStep === APPLICATION_STEPS.length - 1;

  function renderStepContent() {
    switch (currentStep) {
      case 0:
        return (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="产品">{productName}</Descriptions.Item>
            <Descriptions.Item label="险种">
              {formatCategoryLabel(item?.category ?? product?.category)}
            </Descriptions.Item>
            <Descriptions.Item label="承保公司">{product?.insurer ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="保障期限">1 年</Descriptions.Item>
            <Descriptions.Item label="年缴保费">{formatMoney(annualPremium)}</Descriptions.Item>
            <Descriptions.Item label="月均预估">
              {annualPremium ? formatMoney(annualPremium / 12) : '—'}
            </Descriptions.Item>
          </Descriptions>
        );
      case 1:
        return (
          <div className="disclosure">
            <p>为确保您的权益，投保前请确认以下事项：</p>
            <ul>
              <li>投保人、被保险人身份信息真实、准确、有效；</li>
              <li>已仔细阅读并理解保险条款、免责条款及特别约定；</li>
              <li>健康告知内容真实完整，如有隐瞒可能影响理赔；</li>
              <li>同意保险公司为核保目的进行必要的健康信息核实。</li>
            </ul>
          </div>
        );
      case 2:
        return (
          <div className="disclosure">
            <p>请如实回答以下健康告知事项：</p>
            <ul>
              <li>是否患有或曾患有恶性肿瘤、心脑血管疾病等重大疾病？</li>
              <li>近两年内是否因疾病住院或接受手术治疗？</li>
              <li>是否从事高风险职业或参与高危运动？</li>
              <li>是否存在其他可能影响承保的健康异常？</li>
            </ul>
            <p>如存在以上任一情形，请在投保前联系顾问核保确认。</p>
          </div>
        );
      case 3:
        return (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="被保险人">{insuredName}</Descriptions.Item>
            <Descriptions.Item label="产品">{productName}</Descriptions.Item>
            <Descriptions.Item label="保障期限">1 年</Descriptions.Item>
            <Descriptions.Item label="生效日期">次日零时生效</Descriptions.Item>
            <Descriptions.Item label="年缴保费">{formatMoney(annualPremium)}</Descriptions.Item>
          </Descriptions>
        );
      case 4:
        return (
          <div className="pay-summary">
            <p>确认以下投保信息并完成支付：</p>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="产品">{productName}</Descriptions.Item>
              <Descriptions.Item label="被保险人">{insuredName}</Descriptions.Item>
              <Descriptions.Item label="应付金额">{formatMoney(annualPremium)}</Descriptions.Item>
            </Descriptions>
          </div>
        );
      default:
        return null;
    }
  }

  return (
    <div className="application-page">
      <header className="advisor-header">
        <div className="brand">
          <span className="brand__mark"><SafetyCertificateOutlined /></span>
          <span><strong>安心保</strong><small>投保流程</small></span>
        </div>
        <div>
          <span>{session.user.displayName || session.user.username}</span>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回顾问</Button>
        </div>
      </header>

      <main className="application-shell">
        <section className="application-header">
          <div>
            <span>当前产品</span>
            <h1>{productName}</h1>
            <p>投保以页面流程为主，顾问负责解释条款、填写项和注意事项。</p>
          </div>
        </section>

        <section className="application-flow">
          <Steps current={paid ? APPLICATION_STEPS.length : currentStep} items={APPLICATION_STEPS} />
          {error ? <Alert showIcon type="error" message={error} /> : null}
          {paid ? (
            <Alert
              showIcon
              type="success"
              message="投保成功"
              description="保单状态已更新为投保成功，后续可以在理赔演示中查询到这份保单。"
            />
          ) : (
            <div className="application-step-body">
              <h2>{APPLICATION_STEPS[currentStep].title}</h2>
              {loading ? <Spin /> : renderStepContent()}
              {!planId || !itemId ? (
                <Alert
                  showIcon
                  type="warning"
                  message="缺少方案项信息"
                  description="当前入口没有携带 plan_id 或 item_id，无法在支付后更新投保状态。请从保险方案产品卡片进入投保流程。"
                />
              ) : null}
              <div className="application-actions">
                {currentStep > 0 ? (
                  <Button onClick={() => setCurrentStep((step) => step - 1)}>上一步</Button>
                ) : null}
                {isLastStep ? (
                  <Button
                    type="primary"
                    icon={<PayCircleOutlined />}
                    loading={paying}
                    disabled={!planId || !itemId}
                    onClick={() => void pay()}
                  >
                    支付
                  </Button>
                ) : (
                  <Button type="primary" onClick={() => setCurrentStep((step) => step + 1)}>
                    下一步
                  </Button>
                )}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
