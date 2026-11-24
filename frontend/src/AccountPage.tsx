import {
  ArrowLeftOutlined,
  EditOutlined,
  IdcardOutlined,
  MailOutlined,
  PhoneOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Avatar,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Spin,
  Tag,
  message,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { ApiError, getUserProfile, updateUserProfile } from './api';
import { saveSession } from './auth';
import type { AuthSession, UserProfile } from './types';

interface AccountPageProps {
  session: AuthSession;
  onBack: () => void;
}

interface ProfileFormValues {
  display_name: string;
  email: string;
  phone: string;
}

function formatDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : '—';
}

export function AccountPage({ session, onBack }: AccountPageProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ProfileFormValues>();
  const token = session.token;

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getUserProfile(token);
      setProfile(next);
      form.setFieldsValue({
        display_name: next.display_name ?? '',
        email: next.email,
        phone: next.phone ?? '',
      });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '资料加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [form, token]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  async function save(values: ProfileFormValues) {
    setSaving(true);
    try {
      const updated = await updateUserProfile(token, {
        display_name: values.display_name || undefined,
        email: values.email || undefined,
        phone: values.phone || undefined,
      });
      setProfile(updated);
      // 同步本地会话，保证导航栏昵称一致
      saveSession({
        ...session,
        user: {
          ...session.user,
          email: updated.email,
          displayName: updated.display_name,
        },
      });
      message.success('资料已更新');
    } catch (reason) {
      message.error(reason instanceof ApiError ? reason.message : '保存失败，请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); onBack(); }} aria-label="返回安心保首页">
            <span className="brand__mark"><SafetyCertificateOutlined /></span>
            <span><strong>安心保</strong><small>保险优选平台</small></span>
          </a>
          <nav className="site-nav" aria-label="主导航">
            <a href="/" onClick={(event) => { event.preventDefault(); onBack(); }}>返回首页</a>
          </nav>
          <div className="site-actions">
            <span className="user-name">{profile?.display_name || session.user.displayName || session.user.username}</span>
          </div>
        </div>
      </header>

      <main className="account-page">
        {loading ? (
          <div className="account-page__loading"><Spin size="large" /></div>
        ) : error ? (
          <div className="account-page__empty">
            <p>{error}</p>
            <Button onClick={loadProfile}>重新加载</Button>
          </div>
        ) : profile ? (
          <>
            <section className="account-hero">
              <Avatar size={72} icon={<UserOutlined />} />
              <div>
                <h1>{profile.display_name || profile.username}</h1>
                <p>
                  <Tag color={profile.status === 'active' ? 'success' : 'default'}>
                    {profile.status === 'active' ? '账号正常' : '已禁用'}
                  </Tag>
                  <span>注册于 {formatDate(profile.created_at)}</span>
                </p>
              </div>
            </section>

            <Card title={<><IdcardOutlined /> 基本信息</>} className="account-card">
              <Descriptions column={1} size="middle">
                <Descriptions.Item label="用户名">{profile.username}</Descriptions.Item>
                <Descriptions.Item label="昵称">{profile.display_name || '—'}</Descriptions.Item>
                <Descriptions.Item label="邮箱">
                  <MailOutlined /> {profile.email}
                </Descriptions.Item>
                <Descriptions.Item label="手机号">
                  {profile.phone ? <><PhoneOutlined /> {profile.phone}</> : '—'}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            <Card
              title={<><EditOutlined /> 编辑资料</>}
              className="account-card"
            >
              <Form<ProfileFormValues>
                form={form}
                layout="vertical"
                onFinish={save}
                requiredMark={false}
                style={{ maxWidth: 480 }}
              >
                <Form.Item
                  label="昵称"
                  name="display_name"
                  rules={[{ max: 80, message: '昵称最长 80 字' }]}
                >
                  <Input placeholder="请输入昵称" allowClear />
                </Form.Item>
                <Form.Item
                  label="邮箱"
                  name="email"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '邮箱格式不正确' },
                  ]}
                >
                  <Input placeholder="请输入邮箱" allowClear />
                </Form.Item>
                <Form.Item
                  label="手机号"
                  name="phone"
                  rules={[
                    { pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确' },
                  ]}
                >
                  <Input placeholder="请输入 11 位手机号（选填）" allowClear maxLength={11} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={saving}>
                  保存修改
                </Button>
              </Form>
            </Card>
          </>
        ) : null}
      </main>
    </div>
  );
}
