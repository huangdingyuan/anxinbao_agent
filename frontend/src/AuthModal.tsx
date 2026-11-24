import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Form, Input, Modal, message } from 'antd';
import { useState } from 'react';

import { ApiError, login } from './api';
import type { AuthSession } from './types';

interface AuthModalProps {
  open: boolean;
  onCancel: () => void;
  onSuccess: (session: AuthSession) => void;
}

interface AuthFormValues {
  username: string;
  password: string;
}

export function AuthModal({
  open,
  onCancel,
  onSuccess,
}: AuthModalProps) {
  const [loading, setLoading] = useState(false);

  async function submit(values: AuthFormValues) {
    setLoading(true);
    try {
      const profile = await login(values.username, values.password);
      onSuccess({
        user: {
          id: profile.id,
          username: profile.username,
          email: profile.email,
          displayName: profile.display_name,
        },
      });
    } catch (reason) {
      message.error(reason instanceof ApiError ? reason.message : '登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      title={null}
      footer={null}
      width={420}
      onCancel={onCancel}
      destroyOnHidden
      centered
    >
      <div className="auth-modal__header">
        <h2>欢迎来到安心保</h2>
        <p>登录后可使用智能顾问服务</p>
      </div>
      <Form<AuthFormValues>
        layout="vertical"
        initialValues={{ username: 'demo', password: '123456' }}
        onFinish={submit}
        requiredMark={false}
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[{ required: true, message: '请输入用户名' }]}
        >
          <Input prefix={<UserOutlined />} size="large" placeholder="请输入用户名" />
        </Form.Item>
        <Form.Item
          label="密码"
          name="password"
          rules={[{ required: true, min: 6, message: '密码至少需要 6 位' }]}
        >
          <Input.Password prefix={<LockOutlined />} size="large" placeholder="请输入密码" />
        </Form.Item>
        <button className="auth-submit" type="submit" disabled={loading}>
          {loading ? '登录中…' : '登录'}
        </button>
      </Form>
    </Modal>
  );
}
