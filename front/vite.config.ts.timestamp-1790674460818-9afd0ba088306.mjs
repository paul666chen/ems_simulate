// vite.config.ts
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/vite/dist/node/index.js";
import vue from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import vueDevTools from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/vite-plugin-vue-devtools/dist/vite.mjs";
import AutoImport from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/unplugin-auto-import/dist/vite.js";
import Components from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/unplugin-vue-components/dist/vite.js";
import { ElementPlusResolver } from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/unplugin-vue-components/dist/resolvers.js";
import Icons from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/unplugin-icons/dist/vite.js";
import IconsResolver from "file:///F:/GITHUBCODE/EMS/ems_simulate/front/node_modules/unplugin-icons/dist/resolver.js";
var __vite_injected_original_import_meta_url = "file:///F:/GITHUBCODE/EMS/ems_simulate/front/vite.config.ts";
var vite_config_default = defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget = env.VITE_BACKEND_URL || "http://127.0.0.1:8991";
  return {
    build: {
      target: "esnext",
      // 支持最新 ES 特性
      outDir: "../www",
      emptyOutDir: true,
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("node_modules")) {
              if (id.includes("element-plus")) {
                return "element-plus";
              }
              return "vendor";
            }
          }
        }
      }
    },
    server: {
      host: "0.0.0.0",
      port: 8080,
      proxy: {
        "/api": {
          target: backendTarget,
          changeOrigin: true
        },
        "/device": {
          target: backendTarget,
          changeOrigin: true
        },
        "/channel": {
          target: backendTarget,
          changeOrigin: true
        }
      }
    },
    base: "./",
    // 修改这里的值为您想要设置的新路径
    plugins: [
      vue(),
      mode !== "production" && vueDevTools(),
      AutoImport({
        resolvers: [ElementPlusResolver(), IconsResolver()]
      }),
      Components({
        resolvers: [
          ElementPlusResolver(),
          IconsResolver({
            prefix: false,
            // <--
            enabledCollections: ["mdi"]
          })
        ]
      }),
      Icons({
        autoInstall: true
      })
    ],
    envPrefix: ["VITE", "VUE"],
    // 环境变量前缀
    define: {
      "process.env.VITE_APP_BASE_API": JSON.stringify(
        env.VITE_APP_BASE_API || ""
      )
      // 确保有默认值
    },
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", __vite_injected_original_import_meta_url))
      }
    },
    css: {
      preprocessorOptions: {
        scss: {
          api: "modern",
          additionalData: `@use "@/styles/breakpoints.scss" as bp;
`
        }
      }
    }
  };
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJGOlxcXFxHSVRIVUJDT0RFXFxcXEVNU1xcXFxlbXNfc2ltdWxhdGVcXFxcZnJvbnRcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIkY6XFxcXEdJVEhVQkNPREVcXFxcRU1TXFxcXGVtc19zaW11bGF0ZVxcXFxmcm9udFxcXFx2aXRlLmNvbmZpZy50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vRjovR0lUSFVCQ09ERS9FTVMvZW1zX3NpbXVsYXRlL2Zyb250L3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZmlsZVVSTFRvUGF0aCwgVVJMIH0gZnJvbSBcIm5vZGU6dXJsXCI7XHJcblxyXG5pbXBvcnQgeyBkZWZpbmVDb25maWcsIGxvYWRFbnYgfSBmcm9tIFwidml0ZVwiO1xyXG5pbXBvcnQgdnVlIGZyb20gXCJAdml0ZWpzL3BsdWdpbi12dWVcIjtcclxuaW1wb3J0IHZ1ZURldlRvb2xzIGZyb20gXCJ2aXRlLXBsdWdpbi12dWUtZGV2dG9vbHNcIjtcclxuaW1wb3J0IEF1dG9JbXBvcnQgZnJvbSBcInVucGx1Z2luLWF1dG8taW1wb3J0L3ZpdGVcIjtcclxuaW1wb3J0IENvbXBvbmVudHMgZnJvbSBcInVucGx1Z2luLXZ1ZS1jb21wb25lbnRzL3ZpdGVcIjtcclxuaW1wb3J0IHsgRWxlbWVudFBsdXNSZXNvbHZlciB9IGZyb20gXCJ1bnBsdWdpbi12dWUtY29tcG9uZW50cy9yZXNvbHZlcnNcIjtcclxuXHJcbmltcG9ydCBJY29ucyBmcm9tIFwidW5wbHVnaW4taWNvbnMvdml0ZVwiO1xyXG5pbXBvcnQgSWNvbnNSZXNvbHZlciBmcm9tIFwidW5wbHVnaW4taWNvbnMvcmVzb2x2ZXJcIjtcclxuXHJcbmV4cG9ydCBkZWZhdWx0IGRlZmluZUNvbmZpZygoeyBtb2RlIH0pID0+IHtcclxuICAvLyBcdTRGN0ZcdTc1MjggbW9kZSBcdTUzQzJcdTY1NzBcclxuICBjb25zdCBlbnYgPSBsb2FkRW52KG1vZGUsIHByb2Nlc3MuY3dkKCksIFwiXCIpOyAvLyBcdTUyQTBcdThGN0RcdTczQUZcdTU4ODNcdTUzRDhcdTkxQ0ZcclxuICAvLyBUaGUgUHl0aG9uIGJhY2tlbmQgYmluZHMgSVB2NCBleHBsaWNpdGx5LiBVc2luZyBsb2NhbGhvc3QgbWF5IHJlc29sdmUgdG9cclxuICAvLyA6OjEgZmlyc3Qgb24gV2luZG93cy9Ob2RlIGFuZCBtYWtlcyBldmVyeSBwcm94aWVkIHJlcXVlc3QgZmFpbC5cclxuICBjb25zdCBiYWNrZW5kVGFyZ2V0ID0gZW52LlZJVEVfQkFDS0VORF9VUkwgfHwgXCJodHRwOi8vMTI3LjAuMC4xOjg5OTFcIjtcclxuXHJcbiAgcmV0dXJuIHtcclxuICAgIGJ1aWxkOiB7XHJcbiAgICAgIHRhcmdldDogXCJlc25leHRcIiwgLy8gXHU2NTJGXHU2MzAxXHU2NzAwXHU2NUIwIEVTIFx1NzI3OVx1NjAyN1xyXG4gICAgICBvdXREaXI6IFwiLi4vd3d3XCIsXHJcbiAgICAgIGVtcHR5T3V0RGlyOiB0cnVlLFxyXG4gICAgICBjaHVua1NpemVXYXJuaW5nTGltaXQ6IDE1MDAsXHJcbiAgICAgIHJvbGx1cE9wdGlvbnM6IHtcclxuICAgICAgICBvdXRwdXQ6IHtcclxuICAgICAgICAgIG1hbnVhbENodW5rcyhpZCkge1xyXG4gICAgICAgICAgICBpZiAoaWQuaW5jbHVkZXMoXCJub2RlX21vZHVsZXNcIikpIHtcclxuICAgICAgICAgICAgICAvLyBTcGxpdCBFbGVtZW50IFBsdXMgaW50byBpdHMgb3duIGNodW5rXHJcbiAgICAgICAgICAgICAgaWYgKGlkLmluY2x1ZGVzKFwiZWxlbWVudC1wbHVzXCIpKSB7XHJcbiAgICAgICAgICAgICAgICByZXR1cm4gXCJlbGVtZW50LXBsdXNcIjtcclxuICAgICAgICAgICAgICB9XHJcbiAgICAgICAgICAgICAgLy8gR3JvdXAgb3RoZXIgZGVwZW5kZW5jaWVzIGludG8gYSB2ZW5kb3IgY2h1bmtcclxuICAgICAgICAgICAgICByZXR1cm4gXCJ2ZW5kb3JcIjtcclxuICAgICAgICAgICAgfVxyXG4gICAgICAgICAgfSxcclxuICAgICAgICB9LFxyXG4gICAgICB9LFxyXG4gICAgfSxcclxuICAgIHNlcnZlcjoge1xyXG4gICAgICBob3N0OiBcIjAuMC4wLjBcIixcclxuICAgICAgcG9ydDogODA4MCxcclxuICAgICAgcHJveHk6IHtcclxuICAgICAgICBcIi9hcGlcIjoge1xyXG4gICAgICAgICAgdGFyZ2V0OiBiYWNrZW5kVGFyZ2V0LFxyXG4gICAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxyXG4gICAgICAgIH0sXHJcbiAgICAgICAgXCIvZGV2aWNlXCI6IHtcclxuICAgICAgICAgIHRhcmdldDogYmFja2VuZFRhcmdldCxcclxuICAgICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcclxuICAgICAgICB9LFxyXG4gICAgICAgIFwiL2NoYW5uZWxcIjoge1xyXG4gICAgICAgICAgdGFyZ2V0OiBiYWNrZW5kVGFyZ2V0LFxyXG4gICAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxyXG4gICAgICAgIH0sXHJcbiAgICAgIH0sXHJcbiAgICB9LFxyXG4gICAgYmFzZTogXCIuL1wiLCAvLyBcdTRGRUVcdTY1MzlcdThGRDlcdTkxQ0NcdTc2ODRcdTUwM0NcdTRFM0FcdTYwQThcdTYwRjNcdTg5ODFcdThCQkVcdTdGNkVcdTc2ODRcdTY1QjBcdThERUZcdTVGODRcclxuICAgIHBsdWdpbnM6IFtcclxuICAgICAgdnVlKCksXHJcbiAgICAgIG1vZGUgIT09IFwicHJvZHVjdGlvblwiICYmIHZ1ZURldlRvb2xzKCksXHJcbiAgICAgIEF1dG9JbXBvcnQoe1xyXG4gICAgICAgIHJlc29sdmVyczogW0VsZW1lbnRQbHVzUmVzb2x2ZXIoKSwgSWNvbnNSZXNvbHZlcigpXSxcclxuICAgICAgfSksXHJcbiAgICAgIENvbXBvbmVudHMoe1xyXG4gICAgICAgIHJlc29sdmVyczogW1xyXG4gICAgICAgICAgRWxlbWVudFBsdXNSZXNvbHZlcigpLFxyXG4gICAgICAgICAgSWNvbnNSZXNvbHZlcih7XHJcbiAgICAgICAgICAgIHByZWZpeDogZmFsc2UsIC8vIDwtLVxyXG4gICAgICAgICAgICBlbmFibGVkQ29sbGVjdGlvbnM6IFtcIm1kaVwiXSxcclxuICAgICAgICAgIH0pLFxyXG4gICAgICAgIF0sXHJcbiAgICAgIH0pLFxyXG4gICAgICBJY29ucyh7XHJcbiAgICAgICAgYXV0b0luc3RhbGw6IHRydWUsXHJcbiAgICAgIH0pLFxyXG4gICAgXSxcclxuICAgIGVudlByZWZpeDogW1wiVklURVwiLCBcIlZVRVwiXSwgLy8gXHU3M0FGXHU1ODgzXHU1M0Q4XHU5MUNGXHU1MjREXHU3RjAwXHJcbiAgICBkZWZpbmU6IHtcclxuICAgICAgXCJwcm9jZXNzLmVudi5WSVRFX0FQUF9CQVNFX0FQSVwiOiBKU09OLnN0cmluZ2lmeShcclxuICAgICAgICBlbnYuVklURV9BUFBfQkFTRV9BUEkgfHwgXCJcIixcclxuICAgICAgKSwgLy8gXHU3ODZFXHU0RkREXHU2NzA5XHU5RUQ4XHU4QkE0XHU1MDNDXHJcbiAgICB9LFxyXG4gICAgcmVzb2x2ZToge1xyXG4gICAgICBhbGlhczoge1xyXG4gICAgICAgIFwiQFwiOiBmaWxlVVJMVG9QYXRoKG5ldyBVUkwoXCIuL3NyY1wiLCBpbXBvcnQubWV0YS51cmwpKSxcclxuICAgICAgfSxcclxuICAgIH0sXHJcbiAgICBjc3M6IHtcclxuICAgICAgcHJlcHJvY2Vzc29yT3B0aW9uczoge1xyXG4gICAgICAgIHNjc3M6IHtcclxuICAgICAgICAgIGFwaTogXCJtb2Rlcm5cIixcclxuICAgICAgICAgIGFkZGl0aW9uYWxEYXRhOiBgQHVzZSBcIkAvc3R5bGVzL2JyZWFrcG9pbnRzLnNjc3NcIiBhcyBicDtcXG5gLFxyXG4g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
