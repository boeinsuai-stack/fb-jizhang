/* Firebase 项目 fb-jizhang 的连接配置（这些值不是密码，按 Firebase 的设计就是放在网页里的；数据安全靠登录和数据库规则） */
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyCHmPMkaXXBUqC9KXZuCVYVJa2X56zmp7s",
  authDomain: "fb-jizhang.firebaseapp.com",
  projectId: "fb-jizhang",
  storageBucket: "fb-jizhang.firebasestorage.app",
  messagingSenderId: "922400481571",
  appId: "1:922400481571:web:4ed8ab03d66971dc1d6c96",
};
/* 能登录的人：你和老婆。邮箱只以 SHA-256 指纹出现，代码公开时不会暴露邮箱 */
window.APP_CONFIG = {
  // Google Drive 备份用的网页授权编号（OAuth Client ID），不是密码
  googleClientId: "922400481571-jgs1uliu5j063pl0jgttov9ofkfknbn5.apps.googleusercontent.com",
  owners: ["ba5ce8a0e85e31ba5f9ade1d360593ab8ba76047daa6cafdb191cae28e59f97f"],
  // 旧数据里记录的是 Claude 的用户 ID；你登录后沿用它，旧记录才会显示为「我记的」
  legacyIds: { "ba5ce8a0e85e31ba5f9ade1d360593ab8ba76047daa6cafdb191cae28e59f97f": "u_mgqGbjzgSn0HLhOA4YHRKA" },
  displayNames: { "ba5ce8a0e85e31ba5f9ade1d360593ab8ba76047daa6cafdb191cae28e59f97f": "Bowen", "f19d42ce6c113a2a1d663699f426a08113b7e3e5cb0c326a06d03784cd6cbeb6": "老婆" },
};
