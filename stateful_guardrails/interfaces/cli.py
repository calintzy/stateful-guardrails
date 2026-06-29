"""interfaces.cli — sgr CLI 진입점 (typer 기반)."""

from __future__ import annotations

from pathlib import Path

import typer

from stateful_guardrails import __version__

app = typer.Typer(
    name="sgr",
    help="stateful-guardrails: 고객지원 위기 에스컬레이션 조기경보 미들웨어",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _root(
    version: bool = typer.Option(False, "--version", "-v", help="버전 출력 후 종료", is_eager=True),
) -> None:
    """sgr — stateful-guardrails CLI."""
    if version:
        typer.echo(f"stateful-guardrails {__version__}")
        raise typer.Exit()


@app.command("ping-llm")
def ping_llm(
    provider: str = typer.Option("ollama", "--provider", "-p", help="LLM provider (ollama|openai|anthropic)"),
    model: str = typer.Option(None, "--model", "-m", help="사용할 모델명 (미지정 시 provider 기본값)"),
    prompt: str = typer.Option("안녕하세요. 한 줄로 간단히 자기소개 해주세요.", "--prompt", help="테스트 프롬프트"),
) -> None:
    """LLM provider에 테스트 질의를 보내 응답을 출력한다 (연결 확인용)."""
    from stateful_guardrails.adapters.llm import get_adapter

    typer.echo(f"[ping-llm] provider={provider}" + (f" model={model}" if model else ""))
    try:
        adapter = get_adapter(provider, **({"model": model} if model else {}))
        response = adapter.complete(prompt)
        typer.echo(response)
    except NotImplementedError as exc:
        typer.echo(f"[오류] {exc}", err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.echo(f"[오류] LLM 호출 실패: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command("catalog")
def catalog(
    baselines: bool = typer.Option(False, "--baselines", help="baseline 목록 출력"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="상세 설명 포함"),
) -> None:
    """등록된 정책 카탈로그를 출력한다 (ISC-1.3).

    --baselines: B1·B1.5(필수) + B2(가산) baseline 목록 출력 (ISC-1.5).
    """
    if baselines:
        _catalog_baselines(verbose=verbose)
    else:
        _catalog_policies(verbose=verbose)


def _catalog_policies(verbose: bool = False) -> None:
    """ISC-1.3: 각 정책에 (category, stateless|stateful) 태그 출력."""
    from stateful_guardrails.pipeline.catalog import get_all_policies

    policies = get_all_policies()
    typer.echo(f"=== 정책 카탈로그 ({len(policies)}개) ===\n")

    for policy in policies:
        tag = "stateful" if policy.is_stateful else "stateless"
        typer.echo(f"  [{policy.id}]")
        typer.echo(f"    category : {policy.category.value}")
        typer.echo(f"    mode     : {tag}")
        typer.echo(f"    class    : {type(policy).__name__}")
        if verbose:
            typer.echo(f"    Protocol : Policy (evaluate(message, session_state) -> PolicySignal)")
        typer.echo()

    # 카탈로그 요약
    stateless_count = sum(1 for p in policies if not p.is_stateful)
    stateful_count = len(policies) - stateless_count
    typer.echo(f"  합계: stateless={stateless_count}, stateful={stateful_count}")


def _catalog_baselines(verbose: bool = False) -> None:
    """ISC-1.5: B1(필수)·B1.5(필수) + B2(가산) baseline 등록 확인."""
    from stateful_guardrails.pipeline.catalog import get_baselines

    baselines = get_baselines(include_optional=True)
    typer.echo(f"=== Baseline 카탈로그 ({len(baselines)}개) ===\n")

    for b in baselines:
        required_tag = "[필수]" if b.required else "[가산]"
        typer.echo(f"  {b.id} {required_tag}")
        typer.echo(f"    name     : {b.name}")
        typer.echo(f"    mode     : {b.mode}")
        if b.window_size is not None:
            typer.echo(f"    window_K : {b.window_size}  (동결 파라미터 — calibration에서 확정)")
        if verbose:
            typer.echo(f"    desc     : {b.description}")
        if b.note:
            typer.echo(f"    note     : {b.note}")
        typer.echo()

    # 필수 baseline 확인
    required_ids = {b.id for b in baselines if b.required}
    typer.echo("  필수 baseline 등록 확인:")
    for bid in ["B1", "B1.5"]:
        mark = "✓" if bid in required_ids else "✗"
        typer.echo(f"    {mark} {bid}")
    optional_ids = {b.id for b in baselines if not b.required}
    typer.echo("  가산 baseline 등록 확인:")
    for bid in ["B2"]:
        mark = "✓" if bid in optional_ids else "✗"
        typer.echo(f"    {mark} {bid} (가산)")


@app.command("eval")
def eval_cmd(
    mini: bool = typer.Option(False, "--mini", help="미니-eval 게이트 실행 (Phase 2 사활점)"),
    dataset: Path = typer.Option(Path("data"), "--dataset", "-d", help="데이터셋 디렉토리"),
    report: Path = typer.Option(Path("out/mini.md"), "--report", "-r", help="리포트 출력 경로"),
    detectors: str = typer.Option(
        "target_aware,target_agnostic", "--detectors",
        help="detector 목록 (쉼표 구분, ISC-2.5)",
    ),
    calibration: Path = typer.Option(
        Path("data/calibration.json"), "--calibration", help="동결 파라미터 JSON",
    ),
    lambda_sweep_str: str = typer.Option(
        None, "--lambda-sweep",
        help="λ 민감도 곡선 실행 (쉼표 구분 λ 후보, 예: 0.5,0.7,0.9,1.0). ISC-5.6",
    ),
) -> None:
    """미니-eval: STATEFUL−B1/B1.5 델타 산출 + 리포트 생성 (ISC-2.4·2.5·2.7·2.8).

    동결 파라미터(λ·K·N·S_max)는 calibration.json에서 로드(ISC-2.6).
    test-split에서만 평가. B1.5를 못 이기면 thesis 미성립을 정직 명시.
    --lambda-sweep: λ 민감도 곡선 산출 후 --report 경로에 저장하고 종료 (ISC-5.6).
    """
    if not mini:
        typer.echo("[안내] 현재 Phase 2에서는 --mini만 지원합니다.", err=True)
        raise typer.Exit(code=1)

    import json as _json

    from stateful_guardrails.pipeline.engine import EngineParams
    from stateful_guardrails.pipeline.eval import (
        lambda_sweep,
        render_lambda_sweep,
        run_mini_eval,
        thesis_verdict,
        write_report,
    )

    if not calibration.exists():
        typer.echo(f"[오류] 동결 파라미터 파일 없음: {calibration}", err=True)
        raise typer.Exit(code=1)

    calib = _json.loads(calibration.read_text(encoding="utf-8"))
    params = EngineParams(
        lambda_decay=calib.get("lambda_decay", 0.7),
        window_size_k=calib.get("window_size_k", 5),
        state_window_n=calib.get("state_window_n", 10),
        s_max=calib.get("s_max", 1.0),
    )
    fpr_budget = calib.get("fpr_budget", 0.05)
    det_ids = [d.strip() for d in detectors.split(",") if d.strip()]

    # λ-sweep 분기 (ISC-5.6) — 지정 시 곡선만 산출하고 종료
    if lambda_sweep_str:
        try:
            lambdas = [float(x.strip()) for x in lambda_sweep_str.split(",") if x.strip()]
        except ValueError as exc:
            typer.echo(f"[오류] --lambda-sweep 파싱 실패: {exc}", err=True)
            raise typer.Exit(code=1)
        if not lambdas:
            typer.echo("[오류] --lambda-sweep에 유효한 λ 값이 없습니다.", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"=== sgr eval --lambda-sweep (ISC-5.6) ===")
        typer.echo(f"λ 후보: {lambdas}  |  detectors: {det_ids}")
        typer.echo(f"데이터셋: {dataset}  |  FPR 예산: {fpr_budget*100:.0f}%")
        typer.echo("임베딩(bge-m3) 계산 중... (신호는 λ 무관 → 1회 계산 후 재사용)")
        typer.echo()
        sweep = lambda_sweep(
            dataset_dir=dataset,
            base_params=params,
            lambdas=lambdas,
            fpr_budget=fpr_budget,
            detector_ids=det_ids,
        )
        content = render_lambda_sweep(sweep)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(content, encoding="utf-8")
        # 콘솔 요약
        for det_id, d in sweep["by_detector"].items():
            typer.echo(f"[detector={det_id}]")
            typer.echo(f"  고정 recall: B1={d['fixed']['B1']*100:.0f}%  B1.5={d['fixed']['B1.5']*100:.0f}%")
            for r in d["rows"]:
                typer.echo(
                    f"  λ={r['lambda']}  STATEFUL={r['recall_stateful']*100:.0f}%"
                    f"  Δvs B1.5={r['delta_b15']*100:+.1f}%p"
                )
            typer.echo()
        typer.echo(f"λ-sweep 리포트 저장됨: {report}")
        return

    typer.echo("=== sgr eval --mini (Phase 2 사활점) ===")
    typer.echo(f"데이터셋: {dataset}  |  detectors: {det_ids}")
    typer.echo(f"동결 파라미터: λ={params.lambda_decay} K={params.window_size_k} "
               f"N={params.state_window_n} S_max={params.s_max} FPR예산={fpr_budget*100:.0f}%")
    typer.echo("임베딩(bge-m3) 계산 중... (세션 수에 따라 수십 초)")
    typer.echo()

    result = run_mini_eval(dataset, params, fpr_budget=fpr_budget, detector_ids=det_ids)
    write_report(result, report)

    # 콘솔 요약 (델타 컬럼)
    for det_id, dr in result.by_detector.items():
        b1 = dr.metrics["B1"]; b15 = dr.metrics["B1.5"]; st = dr.metrics["STATEFUL"]
        typer.echo(f"[detector={det_id}]")
        typer.echo(f"  recall  B1={b1.recall_all*100:.0f}%  B1.5={b15.recall_all*100:.0f}%  STATEFUL={st.recall_all*100:.0f}%")
        typer.echo(f"  Δrecall STATEFUL−B1={ (st.recall_all-b1.recall_all)*100:+.1f}%p  "
                   f"STATEFUL−B1.5={ (st.recall_all-b15.recall_all)*100:+.1f}%p (사활)")
        typer.echo(f"  K초과 recall  B1.5={b15.recall_over_k*100:.0f}%  STATEFUL={st.recall_over_k*100:.0f}%  "
                   f"(Δ={ (st.recall_over_k-b15.recall_over_k)*100:+.1f}%p, 무한룩백)")
    typer.echo()

    verdicts = thesis_verdict(result)
    typer.echo("Thesis 판정:")
    for det_id, v in verdicts.items():
        typer.echo(f"  {det_id}: {v['verdict']}")
    typer.echo()
    typer.echo(f"리포트 저장됨: {report}")


def _load_escalation_params(calibration: Path) -> tuple[float, float, "EngineParams"]:
    """calibration.json에서 동결 임계 t1·t2 + 엔진 파라미터를 로드한다 (재튜닝 없음)."""
    import json as _json

    from stateful_guardrails.pipeline.engine import EngineParams

    if not calibration.exists():
        typer.echo(f"[오류] 동결 파라미터 파일 없음: {calibration}", err=True)
        raise typer.Exit(code=1)
    calib = _json.loads(calibration.read_text(encoding="utf-8"))
    t1 = calib.get("threshold_t1", 0.7)
    t2 = calib.get("threshold_t2", 0.9)
    params = EngineParams(
        lambda_decay=calib.get("lambda_decay", 0.7),
        window_size_k=calib.get("window_size_k", 5),
        state_window_n=calib.get("state_window_n", 10),
        s_max=calib.get("s_max", 1.0),
    )
    return t1, t2, params


@app.command("escalate")
def escalate_cmd(
    session: str = typer.Option(..., "--session", "-s",
                                help="세션 ID(예: c1-test-004) 또는 .jsonl 파일 경로"),
    dataset: Path = typer.Option(Path("data"), "--dataset", "-d", help="세션 ID 검색 디렉토리"),
    calibration: Path = typer.Option(
        Path("data/calibration.json"), "--calibration", help="동결 파라미터 JSON(t1·t2)",
    ),
) -> None:
    """에스컬레이션 3단계 데모: 누적 위기 S_t를 t1·t2에 매핑해 봇/상담사/매니저 라우팅 (Phase 4).

    탐지 → 액션: 턴별 위기점수·단계 + 'N번째 턴에 상담사/매니저 이관 권고'를 출력한다.
    동결 임계 t1·t2 재사용(재튜닝 없음). 결정적·감사 추적 가능(ISC-4.2).
    """
    from stateful_guardrails.pipeline.escalation import escalate_ref, render_escalation

    t1, t2, params = _load_escalation_params(calibration)
    try:
        result = escalate_ref(session, t1, t2, params, data_dir=dataset)
    except ValueError as exc:
        typer.echo(f"[오류] {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(render_escalation(result))


@app.command("audit")
def audit_cmd(
    session: str = typer.Option(..., "--session", "-s",
                                help="세션 ID 또는 .jsonl 파일 경로"),
    dataset: Path = typer.Option(Path("data"), "--dataset", "-d", help="세션 ID 검색 디렉토리"),
    calibration: Path = typer.Option(
        Path("data/calibration.json"), "--calibration", help="동결 파라미터 JSON(t1·t2)",
    ),
) -> None:
    """감사 로그(ISC-4.2): 각 턴의 판정·조치·증거를 추적 가능한 레코드로 출력한다.

    결정적·재현 가능 — LLM 자율 결정 없이 규칙+누적식으로만 판정한다.
    """
    from stateful_guardrails.pipeline.escalation import escalate_ref, render_audit

    t1, t2, params = _load_escalation_params(calibration)
    try:
        result = escalate_ref(session, t1, t2, params, data_dir=dataset)
    except ValueError as exc:
        typer.echo(f"[오류] {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(render_audit(result))


@app.command("cost-model")
def cost_model_cmd(
    report: Path = typer.Option(Path("out/cost.md"), "--report", "-r", help="리포트 출력 경로"),
    n_values: str = typer.Option("5,10,20,50,100", "--n", help="비교할 세션 턴 수(쉼표 구분)"),
    calibration: Path = typer.Option(
        Path("data/calibration.json"), "--calibration", help="동결 K 로드용 JSON",
    ),
) -> None:
    """경제성 비용 모델: STATEFUL O(N) vs B1.5 O(N·K) vs B2 O(N²) 토큰 비용 비교.

    실측이 아니라 모델 추정(가정 명시). out/cost.md 생성 + 콘솔 요약 (운영 가치 레이어).
    """
    import json as _json

    from stateful_guardrails.pipeline.cost import (
        CostAssumptions,
        build_cost_table,
        render_cost_report,
    )

    k = 5
    if calibration.exists():
        k = _json.loads(calibration.read_text(encoding="utf-8")).get("window_size_k", 5)
    try:
        ns = [int(x.strip()) for x in n_values.split(",") if x.strip()]
    except ValueError as exc:
        typer.echo(f"[오류] --n 파싱 실패: {exc}", err=True)
        raise typer.Exit(code=1)

    a = CostAssumptions(window_k=k)
    content = render_cost_report(a, n_values=ns)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(content, encoding="utf-8")

    typer.echo("=== sgr cost-model (운영 가치 — 추정, 실측 아님) ===")
    typer.echo(f"가정: tokens_per_turn={a.tokens_per_turn} K={a.window_k} "
               f"c_state={a.c_state_tokens} 단가=${a.price_per_1k_tokens_usd}/1k")
    typer.echo(f"  {'N':>4}  {'STATEFUL':>10}  {'B1.5':>10}  {'B2':>10}  {'B2/ST':>7}")
    for r in build_cost_table(ns, a):
        typer.echo(
            f"  {r.n_turns:>4}  {r.cumulative_tokens['STATEFUL']:>10,}  "
            f"{r.cumulative_tokens['B1.5']:>10,}  {r.cumulative_tokens['B2']:>10,}  "
            f"×{r.ratio_vs_stateful['B2']:>6.1f}"
        )
    typer.echo("")
    typer.echo(f"비용 리포트 저장됨: {report}")


@app.command("scan")
def scan(
    mode: str = typer.Option("stateless", "--mode", "-m", help="스캔 모드 (stateless)"),
    input_file: Path = typer.Option(..., "--input", "-i", help="스캔할 JSONL 파일 경로"),
    calibrate: bool = typer.Option(True, "--calibrate/--no-calibrate", help="FPR 캘리브레이션 수행"),
    fpr_budget: float = typer.Option(0.05, "--fpr-budget", help="허용 FPR 예산 (기본 5%)"),
    output: Path = typer.Option(None, "--output", "-o", help="캘리브레이션 결과 저장 경로"),
) -> None:
    """메시지 JSONL 파일을 stateless 정책으로 스캔한다 (ISC-1.4).

    C3 calibration-split에서만 FPR 캘리브레이션 임계를 산출한다.
    test-split은 사용하지 않는다 (ISC-2.6 split 동결).
    """
    if mode != "stateless":
        typer.echo(f"[오류] Phase 1에서는 --mode stateless만 지원합니다 (요청: {mode!r})", err=True)
        raise typer.Exit(code=1)

    if not input_file.exists():
        typer.echo(f"[오류] 입력 파일을 찾을 수 없습니다: {input_file}", err=True)
        raise typer.Exit(code=1)

    from stateful_guardrails.pipeline.scanner import (
        per_threshold_fpr_table,
        run_calibration,
        scan_file_stateless,
    )

    typer.echo(f"=== sgr scan (mode={mode}) ===")
    typer.echo(f"입력: {input_file}")
    typer.echo()

    # 스캔 실행
    typer.echo("[1/3] stateless 정책 스캔 중...")
    results = scan_file_stateless(input_file)
    typer.echo(f"  세션 수: {len(results)}")

    if results:
        risks = [r.max_risk_b1 for r in results]
        typer.echo(f"  B1 max risk — min: {min(risks):.3f}, max: {max(risks):.3f}, avg: {sum(risks)/len(risks):.3f}")

    typer.echo()

    if calibrate:
        typer.echo(f"[2/3] FPR 캘리브레이션 (예산: {fpr_budget*100:.0f}%)...")
        typer.echo()

        # 임계별 FPR 표 출력
        table = per_threshold_fpr_table(results, fpr_budget=fpr_budget)
        typer.echo(f"  {'임계':>6}  {'FP 수':>6}  {'FPR':>8}  {'예산 내':>8}")
        typer.echo(f"  {'-'*6}  {'-'*6}  {'-'*8}  {'-'*8}")
        for row in table:
            mark = "✓" if row["within_budget"] else "✗"
            typer.echo(
                f"  {row['threshold']:>6.1f}  {row['fp_count']:>6d}  {row['fpr']*100:>7.1f}%  {mark:>8}"
            )

        typer.echo()

        # 캘리브레이션 실행 및 저장
        output_path = output or input_file.parent / "calibration.json"
        calib = run_calibration(
            input_path=input_file,
            fpr_budget=fpr_budget,
            output_path=output_path,
        )

        typer.echo("[3/3] 캘리브레이션 결과")
        typer.echo(f"  선택 임계 (t1) : {calib.threshold_t1}")
        typer.echo(f"  고위험 임계 (t2): {calib.threshold_t2}")
        typer.echo(f"  달성 FPR       : {calib.fpr_achieved*100:.1f}% (예산 {fpr_budget*100:.0f}% 내)")
        typer.echo(f"  λ (감쇠)       : {calib.lambda_decay}  (v1 기본값)")
        typer.echo(f"  K (윈도우)     : {calib.window_size_k}  (B1.5 sliding-window)")
        typer.echo(f"  S_max          : {calib.s_max}")
        typer.echo()
        typer.echo(f"  ⚠  {calib.test_split_note}")
        typer.echo()
        typer.echo(f"  저장됨: {output_path}")
    else:
        typer.echo("[2/3] --no-calibrate: 캘리브레이션 건너뜀")

    typer.echo()
    typer.echo("완료.")
