#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

import ze_curioso_auto_v24 as auto


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Zé Curioso Auto V24")
        self.geometry("760x560")
        self.minsize(680, 500)
        self.q = queue.Queue()

        title = tk.Label(self, text="ZÉ CURIOSO AUTO", font=("Sans", 22, "bold"))
        title.pack(pady=(24, 6))
        sub = tk.Label(self, text="Digite a curiosidade e aperte um botão. Roteiro, fundos IA e render são automáticos.")
        sub.pack(pady=(0, 18))

        frame = tk.Frame(self)
        frame.pack(fill="x", padx=28)
        tk.Label(frame, text="Tema / pergunta:", font=("Sans", 11, "bold")).pack(anchor="w")
        self.tema = tk.Entry(frame, font=("Sans", 13))
        self.tema.pack(fill="x", pady=(5, 12), ipady=8)
        self.tema.insert(0, "Por que os gatos seguem a gente até o banheiro?")

        self.btn = tk.Button(
            frame,
            text="GERAR VÍDEO",
            font=("Sans", 14, "bold"),
            height=2,
            command=self.start,
        )
        self.btn.pack(fill="x", pady=(0, 16))

        self.status = tk.Label(frame, text="Pronto.", anchor="w")
        self.status.pack(fill="x")

        self.log = scrolledtext.ScrolledText(self, height=15, font=("Monospace", 9))
        self.log.pack(fill="both", expand=True, padx=28, pady=(10, 24))
        self.after(150, self.poll)

    def write(self, text):
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")

    def start(self):
        tema = self.tema.get().strip()
        if not tema:
            messagebox.showwarning("Zé Curioso", "Digite um tema.")
            return
        self.btn.config(state="disabled")
        self.status.config(text="Gerando... pode levar alguns minutos.")
        self.write("[>] Iniciando geração automática...")
        threading.Thread(target=self.worker, args=(tema,), daemon=True).start()

    def worker(self, tema):
        try:
            final = auto.generate_video(tema)
            self.q.put(("ok", str(final)))
        except Exception as exc:
            self.q.put(("err", str(exc)))

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "ok":
                    self.status.config(text="Vídeo pronto.")
                    self.write(f"[OK] {payload}")
                    messagebox.showinfo("Zé Curioso", f"Vídeo pronto:\n{payload}")
                else:
                    self.status.config(text="Erro na geração.")
                    self.write(f"[ERRO] {payload}")
                    messagebox.showerror("Zé Curioso", payload)
                self.btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(150, self.poll)


if __name__ == "__main__":
    App().mainloop()
