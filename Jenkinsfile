@Library('jenkins-pipeline-shared') _

def isMainline() {
  BRANCH_NAME == 'main'
}

def isFeatureBranch() {
  BRANCH_NAME.startsWith('feature/') || BRANCH_NAME.startsWith('fix/')
}

pipeline {

  agent { label 'docker' }

  options {
    ansiColor colorMapName: 'XTerm'
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
    timeout(time: 30, unit: 'MINUTES')
  }

  triggers {
    // Fires on every push via GitHub webhook.
    // Fallback: polls every 5 minutes if webhook is unavailable.
    githubPush()
    pollSCM('H/5 * * * *')
  }

  environment {
    APP_NAME = 'AutoFix-self-healing-pipeline'
  }

  stages {

    stage('Checkout') {
      steps {
        checkout scm
        echo "Branch: ${BRANCH_NAME} | Commit: ${GIT_COMMIT}"
        script {
          // Abort early if no backend/ files were changed (e.g. autopilot-only push)
          def backendChanged = sh(
            script: "git diff --name-only HEAD~1 HEAD | grep -q '^backend/' && echo yes || echo no",
            returnStdout: true
          ).trim()
          if (backendChanged == 'no') {
            currentBuild.result = 'NOT_BUILT'
            error("No backend/ changes detected — skipping pipeline.")
          }
        }
      }
    }

    stage('Build') {
      agent {
        docker {
          image 'cainc/maven:3.6-jdk17-mysql8'
          reuseNode true
        }
      }
      steps {
        dir('backend') {
          sh './mvnw clean compile -q'
        }
      }
    }

    stage('Test') {
      agent {
        docker {
          image 'cainc/maven:3.6-jdk17-mysql8'
          reuseNode true
        }
      }
      steps {
        dir('backend') {
          sh './mvnw test'
        }
      }
      post {
        always {
          junit 'backend/target/surefire-reports/**/*.xml'
        }
      }
    }

    stage('Package') {
      agent {
        docker {
          image 'cainc/maven:3.6-jdk17-mysql8'
          reuseNode true
        }
      }
      steps {
        dir('backend') {
          sh './mvnw package -DskipTests -q'
        }
      }
      post {
        success {
          archiveArtifacts artifacts: 'backend/target/*.jar', fingerprint: true
        }
      }
    }

    stage('Publish Docker') {
      when {
        expression { isMainline() }
      }
      steps {
        script {
          def image = "${APP_NAME}"
          withDockerRegistry([credentialsId: 'nexus', url: 'https://nexus.cainc.com:5001']) {
            sh "docker buildx build --push --pull \
              -t nexus.cainc.com:5001/${image}:${GIT_COMMIT} \
              -t nexus.cainc.com:5001/${image}:latest \
              ./backend"
          }
        }
      }
    }

    stage('AutoFix — AutoPilot Incident Check') {
      when {
        expression { isMainline() }
      }
      // NOTE: this is a headless agent — there is no interactive Claude Code
      // login here, so AutoFix's *live* diagnosis needs an explicit credential.
      // Without one it still runs but uses its fallback diagnosis (and logs a
      // ⚠ warning). To enable live diagnosis, create a Jenkins secret-text
      // credential and uncomment the environment block below:
      //
      //   environment {
      //     ANTHROPIC_API_KEY = credentials('AutoFix-anthropic-api-key')
      //     // or, for a corporate gateway:
      //     // CLAUDE_BASE_URL = 'https://your-gateway.example.com/anthropic'
      //   }
      steps {
        dir('autopilot') {
          sh '''
            python3 -m venv .venv
            . .venv/bin/activate
            pip install -q -r requirements.txt
            python autopilot.py
          '''
        }
      }
    }

  }

  post {
    always {
      cleanWs()
    }
    success {
      script {
        if (isMainline()) {
          slackSend(
            channel: '#AutoFix-builds',
            color: '#00FF00',
            message: """
              |✅ *${APP_NAME}* build passed
              |Branch: `${BRANCH_NAME}` | Build: #${BUILD_NUMBER}
              |<${JOB_URL}${BUILD_NUMBER}/console|View Console>
            """.stripMargin()
          )
        }
      }
    }
    failure {
      slackSend(
        channel: '#AutoFix-builds',
        color: '#FF0000',
        message: """
          |❌ *${APP_NAME}* build failed
          |Branch: `${BRANCH_NAME}` | Build: #${BUILD_NUMBER}
          |<${JOB_URL}${BUILD_NUMBER}/console|View Console>
        """.stripMargin()
      )
    }
    changed {
      notifyPRStatus()
    }
  }
}
