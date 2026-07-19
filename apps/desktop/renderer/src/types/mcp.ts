export type McpRuntimeStatus = {
  status: "available";
  transport: "stdio";
  tools: string[];
};

export type McpServerConfig = {
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd?: string;
};

export type McpClientConfig = {
  mcpServers: {
    webfa: McpServerConfig;
  };
};
