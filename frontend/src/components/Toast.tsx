import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

const ToastContext = createContext<(text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [text, setText] = useState("");
  const timer = useRef<number>(0);
  const show = useCallback((message: string) => {
    setText(message);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setText(""), 5000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div id="toast" className="toast" role="status" hidden={!text}>
        {text}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
