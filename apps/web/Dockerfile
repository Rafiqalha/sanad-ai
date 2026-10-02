# The build context is the repository ROOT, not this directory, because this
# app resolves its dependencies from the pnpm workspace at the root.
# Build with:  docker build -f apps/web/Dockerfile .
FROM node:24-alpine AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH
RUN corepack enable

FROM base AS build
WORKDIR /srv
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/
RUN pnpm install --frozen-lockfile --filter web...
COPY apps/web ./apps/web
RUN pnpm --filter web build

FROM base AS runner
WORKDIR /srv
ENV NODE_ENV=production
COPY --from=build /srv ./
EXPOSE 3000
CMD ["pnpm", "--filter", "web", "start"]
