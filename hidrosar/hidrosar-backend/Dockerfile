FROM golang:1.27-alpine AS compilar
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /hidrosar-backend .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=compilar /hidrosar-backend /hidrosar-backend
EXPOSE 8080
ENTRYPOINT ["/hidrosar-backend"]
