# Minimal build context used only by the CDK assertion tests.
#
# A Container runtime makes AgentEnvironment upload its build context as an S3
# asset at synth time. Pointing the test spec at this two-file directory keeps
# asset staging instant instead of copying the whole repository.
FROM public.ecr.aws/docker/library/python:3.13-slim
COPY main.py /app/main.py
CMD ["python", "/app/main.py"]
