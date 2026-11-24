import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  CustomerServiceOutlined,
  FileTextOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { Button } from 'antd';

interface ServicePageProps {
  onBack: () => void;
  onProducts: () => void;
}

const SERVICES = [
  {
    icon: <AppstoreOutlined />,
    title: '多家产品',
    desc: '覆盖常见保障需求',
    detail: '汇集多家保险公司产品，覆盖医疗、重疾、寿险、意外等常见保障需求，按需比较选择。',
  },
  {
    icon: <FileTextOutlined />,
    title: '信息清晰',
    desc: '条款重点集中展示',
    detail: '把复杂的保险条款做重点提炼，突出保障责任与免责条款，让关键信息一目了然。',
  },
  {
    icon: <CustomerServiceOutlined />,
    title: '顾问协助',
    desc: '按预算和需求组合建议',
    detail: '智能顾问结合你的年龄、预算与保障偏好，给出更适合的组合投保建议。',
  },
];

export function ServicePage({ onBack, onProducts }: ServicePageProps) {
  return (
    <div className="page-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); onBack(); }} aria-label="安心保首页">
            <span className="brand__mark"><SafetyCertificateOutlined /></span>
            <span><strong>安心保</strong><small>保险优选平台</small></span>
          </a>
          <nav className="site-nav" aria-label="主导航">
            <a href="/#products" onClick={(event) => { event.preventDefault(); onProducts(); }}>保险产品</a>
            <a className="is-active" href="/service" onClick={(event) => event.preventDefault()}>服务保障</a>
          </nav>
          <div className="site-actions">
            <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回首页</Button>
          </div>
        </div>
      </header>

      <main className="service-page">
        <section className="service-hero">
          <h1>服务保障</h1>
          <p>让每一次选择更省心，让每一份保障更清晰</p>
        </section>

        <section className="service-grid">
          {SERVICES.map((service) => (
            <div className="service-card" key={service.title}>
              <span className="service-card__icon">{service.icon}</span>
              <strong>{service.title}</strong>
              <span className="service-card__desc">{service.desc}</span>
              <p>{service.detail}</p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
