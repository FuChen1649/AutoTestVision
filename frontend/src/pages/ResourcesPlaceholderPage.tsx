import "./PlatformPages.css";

export default function ResourcesPlaceholderPage() {
  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>资源依赖</h2>
      </div>

      <div className="platform-card">
        <h3>即将上线</h3>
        <p>
          资源依赖模块将统一管理测试所需的 APK、账号凭证、环境变量、Mock 服务等依赖项，并支持 Case / 任务级别的依赖声明与校验。
        </p>
      </div>

      <div className="platform-card">
        <h3>规划能力</h3>
        <ul style={{ color: "#9ca3af", fontSize: "0.875rem", lineHeight: 1.8, margin: "8px 0 0", paddingLeft: 20 }}>
          <li>依赖包版本管理与安装脚本</li>
          <li>测试账号 / Token 安全存储</li>
          <li>环境变量与配置文件模板</li>
          <li>任务执行前依赖检查</li>
        </ul>
      </div>
    </div>
  );
}
