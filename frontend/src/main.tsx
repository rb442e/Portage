import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppProvider } from "./store";
import { CopilotProvider } from "./copilot/CopilotContext";
import { AuthProvider } from "./auth/AuthContext";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AppProvider>
          <CopilotProvider>
            <App />
          </CopilotProvider>
        </AppProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
