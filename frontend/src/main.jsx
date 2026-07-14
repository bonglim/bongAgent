/**
 * Bong에이전트 single-page application의 React 진입점.
 *
 * Vite가 제공하는 ``#root`` DOM 노드에 최상위 ``App`` 컴포넌트를 mount한다.
 * StrictMode를 사용해 개발 중 부수효과와 deprecated API 사용을 더 빨리 발견한다.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// 사용 예: `npm run dev`로 Vite를 시작하면 index.html의 #root에 App이 한 번 mount된다.
// StrictMode는 개발 환경에서 effect 재실행 가능성이 있으므로 API mutation은 사용자 이벤트에서 수행한다.
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
