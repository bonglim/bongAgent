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

// Vite index.html의 root element에 전체 대시보드 애플리케이션을 연결한다.
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
